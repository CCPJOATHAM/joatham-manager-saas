import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django import forms
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext, override

from core.forms import EntrepriseSettingsForm, ExchangeRateManualForm
from core.models import ActivityLog, ExchangeRate, PlatformSettings
from core.services.currency import format_decimal_number, get_currency_code
from core.services.exchange_rates import ExchangeRateUnavailable, convert_amount
from core.services.product_policy import get_module_access_state
from core.services.subscription import (
    activate_subscription_for_entreprise, build_subscription_payment_estimate,
    build_subscription_pricing_matrix, get_default_paid_plans, get_or_create_free_plan,
    get_subscription_price_usd,
)
from core.services.world import get_country_choices
from joatham_billing.models import Facture, LigneFacture
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_dashboard.services.navigation import build_navigation_for_request
from joatham_users.models import Abonnement
from joatham_users.permissions import user_has_permission


class FourRegressionTests(TestCase):
    def setUp(self):
        self.company = create_entreprise("Société Àvenir conservée")
        self.company.devise = "FC"
        self.company.referentiel_comptable = "pcg"
        self.company.save()
        self.owner = create_user("regression-owner", "proprietaire", self.company)
        self.manager = create_user("regression-manager", "gestionnaire", self.company)
        self.accountant = create_user("regression-accountant", "comptable", self.company)
        self.plans = {data["code"]: Abonnement.objects.create(**data) for data in get_default_paid_plans()}
        activate_subscription_for_entreprise(entreprise=self.company, plan=self.plans["premium"], utilisateur=self.owner)
        PlatformSettings.get_solo()

    def language(self, language):
        self.owner.preferred_language = language
        self.owner.save(update_fields=["preferred_language"])
        self.client.force_login(self.owner)
        self.client.post(reverse("set_language"), {"language": language, "next": reverse("company_settings")})

    def company_payload(self):
        return {name: getattr(self.company, name) for name in EntrepriseSettingsForm.Meta.fields if name != "logo"}

    def test_bilingual_country_select_preserves_currency_accounting_and_customer_data(self):
        for language in ("fr", "en"):
            with self.subTest(language=language), override(language):
                self.language(language)
                response = self.client.get(reverse("company_settings"))
                field = response.context["form"].fields["pays"]
                self.assertIsInstance(field.widget, forms.Select)
                self.assertEqual(list(field.choices)[1:], get_country_choices())
                self.assertContains(response, '<option value="RDC" selected>RDC</option>', html=True)
                for country, currency in (("France", "FC"), ("Cameroun", "EUR")):
                    payload = {**self.company_payload(), "pays": country, "devise": currency}
                    response = self.client.post(reverse("company_settings"), payload)
                    self.assertEqual(response.status_code, 302)
                    self.company.refresh_from_db()
                    self.assertEqual((self.company.pays, self.company.devise, self.company.referentiel_comptable), (country, currency, "pcg"))
                    self.assertEqual(self.company.nom, "Société Àvenir conservée")
                self.company.pays, self.company.devise = "RDC", "FC"
                self.company.save()

    def test_legacy_country_remains_selected_but_new_unknown_country_is_rejected(self):
        self.company.pays = "CD"
        self.company.save()
        form = EntrepriseSettingsForm(instance=self.company)
        self.assertIn(("CD", "CD"), form.fields["pays"].choices)
        self.assertEqual(form["pays"].value(), "CD")
        for language in ("fr", "en"):
            with self.subTest(language=language), override(language):
                form = EntrepriseSettingsForm({**self.company_payload(), "pays": "Unknown-new-country"}, instance=self.company)
                self.assertFalse(form.is_valid())
                self.assertIn("pays", form.errors)
        self.company.refresh_from_db()
        self.assertEqual((self.company.pays, self.company.devise), ("CD", "FC"))

    def test_currency_cycle_uses_iso_rates_without_changing_reference_prices(self):
        rates = {"CDF": Decimal("2800"), "XAF": Decimal("600"), "XOF": Decimal("610"), "EUR": Decimal("0.9"), "USD": Decimal("1")}
        for currency, rate in rates.items():
            if currency != "USD":
                ExchangeRate.objects.create(devise_source="USD", devise_cible=currency, taux=rate, date_taux=timezone.now())
        plan = self.plans["premium"]
        monthly = Decimal(str(plan.prix)).quantize(Decimal(".01"))
        with patch("core.services.exchange_rates._fetch_rate_from_provider", side_effect=AssertionError("Cached rates expected")):
            for language in ("fr", "en"):
                for raw, canonical in (("FC", "CDF"), ("FCFA", "XAF"), ("FC", "CDF"), ("XOF", "XOF"), ("EUR", "EUR"), ("USD", "USD")):
                    with self.subTest(language=language, currency=raw), override(language):
                        self.company.devise = raw
                        self.company.save(update_fields=["devise"])
                        estimate = build_subscription_payment_estimate(entreprise=self.company, plan=plan, duree="mensuel")
                        self.assertEqual(get_currency_code(self.company), canonical)
                        self.assertEqual(estimate["currency_code"], canonical)
                        self.assertEqual(estimate["exchange_rate"], rates[canonical])
                        self.assertEqual(estimate["amount_usd"], monthly)
                        self.assertEqual(estimate["estimated_amount"], (monthly * rates[canonical]).quantize(Decimal(".01")))
                        matrix = build_subscription_pricing_matrix(entreprise=self.company, plans=[plan])
                        self.assertNotIn('"None"', json.dumps(matrix, default=str))
        self.assertEqual(get_subscription_price_usd(plan=plan, duree="annuel"), (monthly * 12 * Decimal(".80")).quantize(Decimal(".01")))
        plan.refresh_from_db()
        self.assertEqual(Decimal(str(plan.prix)).quantize(Decimal(".01")), monthly)

    def test_bilingual_missing_rate_uses_null_and_explicit_unavailable_display(self):
        with patch("core.services.exchange_rates._fetch_rate_from_provider", side_effect=ExchangeRateUnavailable("offline")):
            for language in ("fr", "en"):
                with self.subTest(language=language), override(language):
                    self.language(language)
                    matrix = build_subscription_pricing_matrix(entreprise=self.company, plans=[self.plans["premium"]])
                    for estimate in matrix.values():
                        self.assertIsNone(estimate["estimated_amount"])
                        self.assertIsNone(estimate["exchange_rate"])
                        self.assertGreater(Decimal(estimate["amount_usd"]), 0)
                    response = self.client.get(reverse("subscription_overview"))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, gettext("Conversion temporairement indisponible."))
                    self.assertNotContains(response, "None")
                    response = self.client.get(reverse("subscription_payment_create"))
                    self.assertEqual(response.status_code, 200)
                    self.assertNotContains(response, '"None"')
                    self.assertContains(response, '"estimated_amount": null')

    def test_invalid_provider_rates_are_unavailable_not_zero_or_nan(self):
        for rate in ("0", "-1", "NaN", "Infinity"):
            with self.subTest(rate=rate), patch("core.services.exchange_rates.requests.get", return_value=Mock(status_code=200, json=lambda: {"result": "success", "rates": {"CDF": rate}})):
                with self.assertRaises(ExchangeRateUnavailable):
                    convert_amount(Decimal("10"), "USD", "CDF")

    def test_legacy_manual_rate_is_reused_without_rewriting_history(self):
        rate = ExchangeRate.objects.create(devise_source="USD", devise_cible="FC", taux=Decimal("2800"), date_taux=timezone.now())
        with patch("core.services.exchange_rates._fetch_rate_from_provider", side_effect=AssertionError("Legacy cache expected")):
            result = convert_amount(Decimal("10"), "USD", "CDF")
        self.assertEqual((result.amount, result.target_currency), (Decimal("28000.00"), "CDF"))
        rate.refresh_from_db()
        self.assertEqual(rate.devise_cible, "FC")

    def test_manual_rate_form_normalizes_symbols_and_rejects_nonpositive_rates(self):
        for language in ("fr", "en"):
            with self.subTest(language=language), override(language):
                for value in ("0", "-1"):
                    form = ExchangeRateManualForm({"devise_source": "USD", "devise_cible": "FC", "taux": value, "actif": True})
                    self.assertFalse(form.is_valid())
                    self.assertIn("taux", form.errors)
                form = ExchangeRateManualForm({"devise_source": "USD", "devise_cible": "FC", "taux": "2800", "actif": True})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["devise_cible"], "CDF")

    def test_bilingual_invoice_storage_matches_multiple_line_decimal_preview(self):
        for language in ("fr", "en"):
            with self.subTest(language=language), override(language):
                self.language(language)
                response = self.client.get(reverse("add_facture"))
                self.assertContains(response, 'const currencyCode = "CDF"')
                self.assertContains(response, "invoice-totals.js")
                response = self.client.post(reverse("add_facture"), {
                    "client_nom": "Client français conservé", "tva": "16", "remise": "5", "rabais": "2", "ristourne": "1",
                    "designation[]": ["Article français conservé", "Second article"],
                    "quantite[]": ["105", "2"], "prix[]": ["500", "99.99"],
                    "product_id[]": ["", ""], "service_id[]": ["", ""],
                })
                self.assertEqual(response.status_code, 302)
                invoice = Facture.objects.latest("pk")
                self.assertEqual(invoice.total_ht, Decimal("52699.98"))
                self.assertEqual(format_decimal_number(invoice.total_tva), "8 432,00" if language == "fr" else "8,432.00")
                self.assertEqual(format_decimal_number(invoice.total_reduction), "4 216,00" if language == "fr" else "4,216.00")
                self.assertEqual(format_decimal_number(invoice.total_net), "56 915,98" if language == "fr" else "56,915.98")
                self.assertEqual(invoice.client_display, "Client français conservé")

    def test_navigation_matches_primary_modules_permissions_and_plans_in_both_languages(self):
        primary = {
            "clients": ("clients.view", "client_list"), "services": ("services.view", "service_list"),
            "billing": ("billing.view", "facture_list"), "proformas": ("billing.view", "proforma_list"),
            "products": ("products.view", "product_list"), "expenses": ("expenses.view", "depenses"),
            "caisse": ("caisse.view", "caisse_list"), "payments": ("payments.view", "payment_list"),
            "apprenants": ("apprenants.view", "apprenant_list"), "accounting": ("accounting.view", "compta_dashboard"),
            "audit": ("audit.view", "activity_log_list"), "rh": ("rh.view", "rh_employe_list"),
            "advanced_reports": ("reports.advanced_view", "advanced_reports"),
        }
        plans = [get_or_create_free_plan(), *self.plans.values()]
        for plan in plans:
            activate_subscription_for_entreprise(entreprise=self.company, plan=plan, utilisateur=self.owner)
            self.company.refresh_from_db()
            for user in (self.owner, self.manager, self.accountant):
                user.entreprise = self.company
                request = RequestFactory().get("/")
                request.user = user
                for language in ("fr", "en"):
                    with self.subTest(plan=plan.code, role=user.role, language=language), override(language):
                        items = build_navigation_for_request(request)
                        urls = {item["url"] for item in items if not item["is_disabled"]}
                        for module, (permission, route) in primary.items():
                            allowed_role = user_has_permission(user, permission)
                            if allowed_role and get_module_access_state(self.company, module)["allowed"]:
                                self.assertIn(reverse(route), urls)
                            if not allowed_role:
                                self.assertNotIn(reverse(route), urls)

    def test_bilingual_edit_preserves_zero_vat_and_machine_readable_prices(self):
        self.company.taux_tva_defaut = Decimal("18.50")
        self.company.save()
        invoice = Facture.objects.create(entreprise=self.company, client_nom="Client français", tva=0)
        LigneFacture.objects.create(facture=invoice, designation="Article conservé", quantite=2, prix_unitaire=Decimal("500.25"))
        for language in ("fr", "en"):
            with self.subTest(language=language), override(language):
                self.language(language)
                response = self.client.get(reverse("edit_facture", args=[invoice.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id="tva" value="0')
                self.assertContains(response, 'value="500.25"')
                self.assertNotContains(response, 'value="500,25"')

    def test_accountant_audit_link_does_not_grant_access_to_manager_or_other_company(self):
        external = create_entreprise("Autre entreprise privée")
        ActivityLog.objects.create(entreprise=external, action="private-note", module="billing", description="Confidentiel entreprise externe")
        self.client.force_login(self.accountant)
        response = self.client.get(reverse("activity_log_list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Confidentiel entreprise externe")
        self.assertContains(response, f'href="{reverse("activity_log_list")}"')
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("activity_log_list")).status_code, 403)
