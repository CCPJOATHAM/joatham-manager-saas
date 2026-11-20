import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext, override

from core.forms import EntrepriseSettingsForm
from core.models import ExchangeRate, PlatformSettings
from core.services.exchange_rates import ExchangeRateUnavailable, _fetch_exchangerate_api_rate
from core.services.subscription import (
    activate_subscription_for_entreprise, build_subscription_payment_estimate,
    get_default_paid_plans, get_subscription_price_usd,
)
from core.services.world import CURRENCY_DETAILS, get_currency_choices, normalize_currency_code
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement


class CurrencyInventoryTests(SimpleTestCase):
    def test_audited_inventory_matches_every_currency_in_the_application(self):
        codes = [code for code, _ in get_currency_choices()]
        inventory = json.loads((settings.BASE_DIR / "docs/currency-coverage.json").read_text(encoding="utf-8"))
        self.assertEqual([row["code"] for row in inventory["currencies"]], codes)
        self.assertEqual(len(codes), len(set(codes)))
        for code in codes:
            self.assertRegex(code, r"^[A-Z]{3}$")
            self.assertEqual(normalize_currency_code(f" {code.lower()} "), code)
            self.assertTrue(CURRENCY_DETAILS[code]["name"])
            self.assertTrue(CURRENCY_DETAILS[code]["symbol"])

    def test_provider_parser_accepts_every_supported_target_without_a_regional_whitelist(self):
        rates = {code: str(Decimal(index + 1) / 10) for index, (code, _) in enumerate(get_currency_choices())}
        rates["USD"] = "1"
        payload = {"result": "success", "base_code": "USD", "rates": rates}
        with patch("core.services.exchange_rates.requests.get", return_value=Mock(status_code=200, json=lambda: payload)), patch("core.services.exchange_rates.logger"):
            for code, _ in get_currency_choices():
                with self.subTest(currency=code):
                    rate, _ = _fetch_exchangerate_api_rate("USD", code, "")
                    self.assertEqual(rate, Decimal(rates[code]))

    def test_provider_response_with_another_base_never_produces_a_misleading_amount(self):
        for base in ("EUR", None, True, 123):
            with self.subTest(base=base), patch("core.services.exchange_rates.requests.get", return_value=Mock(status_code=200, json=lambda: {"result": "success", "base_code": base, "rates": {"JPY": 150}})), patch("core.services.exchange_rates.logger"):
                with self.assertRaises(ExchangeRateUnavailable):
                    _fetch_exchangerate_api_rate("USD", "JPY", "")


class AllCurrencyConversionTests(TestCase):
    def setUp(self):
        self.company = create_entreprise("Société internationale conservée")
        self.owner = create_user("currency-coverage", "proprietaire", self.company)
        self.plan = Abonnement.objects.create(**next(data for data in get_default_paid_plans() if data["code"] == "premium"))
        activate_subscription_for_entreprise(entreprise=self.company, plan=self.plan, utilisateur=self.owner)
        PlatformSettings.get_solo()

    def quote(self, code, rate):
        ExchangeRate.objects.create(devise_source="USD", devise_cible=code, taux=Decimal(rate), source_provider="test-fixture", date_taux=timezone.now())

    def estimate(self, period="mensuel"):
        return build_subscription_payment_estimate(entreprise=self.company, plan=self.plan, duree=period)

    def test_all_currencies_convert_from_available_rates_in_both_languages(self):
        rates = {code: (Decimal(index + 1) / 7).quantize(Decimal(".00000001")) for index, (code, _) in enumerate(get_currency_choices())}
        rates["USD"] = Decimal("1")
        ExchangeRate.objects.bulk_create([
            ExchangeRate(devise_source="USD", devise_cible=code, taux=rate, source_provider="test-fixture", date_taux=timezone.now())
            for code, rate in rates.items() if code != "USD"
        ])
        with patch("core.services.exchange_rates._fetch_rate_from_provider", side_effect=AssertionError("A valid cached rate must be reused")):
            for language in ("fr", "en"):
                with override(language):
                    for code, rate in rates.items():
                        self.company.devise = code
                        for period in ("mensuel", "annuel"):
                            with self.subTest(language=language, currency=code, period=period):
                                estimate = self.estimate(period)
                                reference = get_subscription_price_usd(plan=self.plan, duree=period)
                                self.assertEqual(estimate["currency_code"], code)
                                self.assertEqual(estimate["exchange_rate"], rate)
                                self.assertEqual(estimate["amount_usd"], reference)
                                self.assertEqual(estimate["estimated_amount"], (reference * rate).quantize(Decimal(".01")))

    def test_missing_rates_are_unavailable_for_every_currency_except_usd_identity(self):
        with patch("core.services.exchange_rates._fetch_rate_from_provider", side_effect=ExchangeRateUnavailable("offline")):
            for language in ("fr", "en"):
                with override(language):
                    for code, _ in get_currency_choices():
                        with self.subTest(language=language, currency=code):
                            self.company.devise = code
                            estimate = self.estimate()
                            if code == "USD":
                                self.assertEqual(estimate["exchange_rate"], Decimal("1"))
                                self.assertEqual(estimate["estimated_amount"], estimate["amount_usd"])
                            else:
                                self.assertIsNone(estimate["estimated_amount"])
                                self.assertIsNone(estimate["exchange_rate"])
                                self.assertEqual(estimate["exchange_source"], "unavailable")
                            self.assertEqual(estimate["currency_code"], code)

    def test_successive_profile_changes_recover_immediately_after_missing_rate_fr_en(self):
        rates = {"EUR": Decimal(".9"), "GBP": Decimal(".8"), "JPY": Decimal("150"), "CAD": Decimal("1.35"),
                 "CHF": Decimal(".88"), "CNY": Decimal("7.2"), "KWD": Decimal(".3"), "ZAR": Decimal("18"), "USD": Decimal("1")}
        for code, rate in rates.items():
            if code != "USD":
                self.quote(code, rate)
        reference = get_subscription_price_usd(plan=self.plan, duree="mensuel")
        sequence = ("EUR", "KPW", "CAD", "EUR", "JPY", "KPW", "JPY", "GBP", "CHF", "CNY", "KWD", "ZAR", "USD")
        with patch("core.services.exchange_rates._fetch_rate_from_provider", side_effect=ExchangeRateUnavailable("offline")) as provider:
            for language in ("fr", "en"):
                with override(language):
                    self.owner.preferred_language = language
                    self.owner.save(update_fields=["preferred_language"])
                    self.client.force_login(self.owner)
                    self.client.post(reverse("set_language"), {"language": language, "next": reverse("company_settings")})
                    for code in sequence:
                        with self.subTest(language=language, currency=code):
                            payload = {field: getattr(self.company, field) for field in EntrepriseSettingsForm.Meta.fields if field != "logo"}
                            response = self.client.post(reverse("company_settings"), {**payload, "devise": code})
                            self.assertEqual(response.status_code, 302)
                            self.company.refresh_from_db()
                            self.assertEqual(self.company.devise, code)
                            calls_before = provider.call_count
                            for route in ("subscription_overview", "subscription_plan_list", "subscription_payment_create"):
                                response = self.client.get(reverse(route))
                                self.assertEqual(response.status_code, 200)
                                self.assertNotContains(response, "None")
                                if code == "KPW":
                                    self.assertContains(response, gettext("Conversion temporairement indisponible.").rstrip("."))
                                if route == "subscription_payment_create":
                                    data = response.context["pricing_matrix"][f"{self.plan.pk}:mensuel"]
                                    self.assertEqual(data["currency_code"], code)
                                    self.assertEqual(Decimal(data["amount_usd"]), reference)
                                    if code == "KPW":
                                        self.assertIsNone(data["estimated_amount"])
                                        self.assertIsNone(data["exchange_rate"])
                                    else:
                                        self.assertEqual(Decimal(data["estimated_amount"]), (reference * rates[code]).quantize(Decimal(".01")))
                            if code != "KPW":
                                self.assertEqual(provider.call_count, calls_before, "Returning to an available rate must not refetch the provider")
        self.plan.refresh_from_db()
        self.assertEqual(get_subscription_price_usd(plan=self.plan, duree="mensuel"), reference)
        self.assertEqual(get_subscription_price_usd(plan=self.plan, duree="annuel"), (reference * 12 * Decimal(".80")).quantize(Decimal(".01")))
        self.assertEqual(self.company.nom, "Société internationale conservée")

    def test_manual_rate_appearing_after_unavailable_is_used_on_next_estimate(self):
        self.company.devise = "KPW"
        with patch("core.services.exchange_rates._fetch_rate_from_provider", side_effect=ExchangeRateUnavailable("offline")):
            self.assertIsNone(self.estimate()["estimated_amount"])
        self.quote("KPW", "900")
        with patch("core.services.exchange_rates._fetch_rate_from_provider", side_effect=AssertionError("Manual rate must be immediately available")):
            estimate = self.estimate()
        self.assertEqual(estimate["exchange_rate"], Decimal("900"))
        self.assertEqual(estimate["estimated_amount"], (estimate["amount_usd"] * 900).quantize(Decimal(".01")))
