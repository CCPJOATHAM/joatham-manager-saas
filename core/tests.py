from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import TestCase, override_settings
from django.urls import reverse

from datetime import date, timedelta
from decimal import Decimal
import hashlib
import hmac
import json
from unittest.mock import Mock, patch

import requests

from joatham_billing.models import PaiementFacture
from joatham_billing.services.facturation import register_payment
from joatham_billing.tests.factories import create_client, create_entreprise, create_facture_sample, create_user
from joatham_clients.services.clients_service import create_client_for_entreprise
from joatham_users.models import Abonnement, AbonnementEntreprise, User

from .models import ActivityLog, ExchangeRate, PaiementAbonnement, PlatformSettings
from .selectors.audit import (
    get_activity_actions_for_entreprise,
    get_activity_logs_by_entreprise,
    get_activity_modules_for_entreprise,
    get_inscription_billing_history,
    get_activity_roles_for_entreprise,
    get_activity_users_for_entreprise,
)
from .services.tenancy import (
    get_object_for_entreprise,
    get_subscription_access_state,
    get_user_entreprise_or_raise,
    scope_queryset_to_entreprise,
)
from .services.subscription import (
    activate_subscription_for_entreprise,
    build_subscription_payment_estimate,
    create_subscription_payment_request,
    get_default_paid_plans,
    get_subscription_price_usd,
    refuse_subscription_payment,
    validate_subscription_payment,
)
from .services.payment_providers import (
    CINETPAY_NOTIFICATION_HMAC_FIELDS,
    PaymentProviderError,
    get_automatic_payment_configuration_diagnostic,
)
from .services.subscription_payments import create_automatic_subscription_payment_request
from .services.product_policy import get_module_access_state as get_product_module_access_state
from .services.currency import get_currency_code
from .services.exchange_rates import convert_amount, get_plan_price_for_company
from .services.language import LANGUAGE_SESSION_KEY, get_request_language, persist_language_preference
from joatham_users.permissions import user_has_permission


class LanguagePreferenceTests(TestCase):
    def _request(self, user, session=None, cookies=None):
        request = Mock()
        request.user = user
        request.session = session or {}
        request.COOKIES = cookies or {}
        return request

    def test_user_language_wins_over_stale_session_for_authenticated_user(self):
        entreprise = create_entreprise("Entreprise Langue")
        user = create_user("lang-user", "proprietaire", entreprise)
        user.preferred_language = "en"
        user.save(update_fields=["preferred_language"])
        request = self._request(user, session={LANGUAGE_SESSION_KEY: "fr"})

        self.assertEqual(get_request_language(request), "en")

    def test_persist_language_preference_accepts_en_and_pt(self):
        entreprise = create_entreprise("Entreprise Langues")

        for language_code in ("en", "pt"):
            user = create_user(f"lang-{language_code}", "proprietaire", entreprise)
            request = self._request(user)

            self.assertEqual(persist_language_preference(request, language_code), language_code)
            user.refresh_from_db()
            self.assertEqual(user.preferred_language, language_code)
            self.assertEqual(request.session[LANGUAGE_SESSION_KEY], language_code)


class TenancyServiceTests(TestCase):
    def setUp(self):
        self.entreprise_a = create_entreprise("Entreprise A")
        self.entreprise_b = create_entreprise("Entreprise B")
        self.user_a = create_user("tenant-a", "proprietaire", self.entreprise_a)
        self.client_a = create_client(self.entreprise_a, "Client A")
        self.client_b = create_client(self.entreprise_b, "Client B")

    def test_get_user_entreprise_or_raise_returns_bound_entreprise(self):
        self.assertEqual(get_user_entreprise_or_raise(self.user_a), self.entreprise_a)

    def test_get_user_entreprise_or_raise_rejects_missing_tenant(self):
        user_without_company = create_user("tenant-none", "gestionnaire", self.entreprise_a)
        user_without_company.entreprise = None
        user_without_company.save(update_fields=["entreprise"])

        with self.assertRaises(PermissionDenied):
            get_user_entreprise_or_raise(user_without_company)

    def test_get_user_entreprise_or_raise_rejects_super_admin_platform_user(self):
        super_admin = create_user("platform-admin", "super_admin", self.entreprise_a)

        with self.assertRaises(PermissionDenied):
            get_user_entreprise_or_raise(super_admin)

    def test_super_admin_permissions_remain_platform_only(self):
        super_admin = create_user("platform-root", "super_admin", self.entreprise_a)
        super_admin.is_superuser = True
        super_admin.save(update_fields=["is_superuser"])

        self.assertTrue(user_has_permission(super_admin, "superadmin.view"))
        self.assertFalse(user_has_permission(super_admin, "clients.view"))

    def test_scope_queryset_to_entreprise_filters_cross_tenant_rows(self):
        scoped = scope_queryset_to_entreprise(self.client_a.__class__.objects.all(), self.entreprise_a)
        self.assertEqual(list(scoped), [self.client_a])

    def test_get_object_for_entreprise_prevents_cross_tenant_access(self):
        found = get_object_for_entreprise(self.client_a.__class__.objects.all(), self.entreprise_a, id=self.client_a.id)
        self.assertEqual(found, self.client_a)

        with self.assertRaises(Http404):
            get_object_for_entreprise(self.client_a.__class__.objects.all(), self.entreprise_a, id=self.client_b.id)

    def test_subscription_access_state_reports_missing_subscription(self):
        state = get_subscription_access_state(self.entreprise_a, user=self.user_a)
        self.assertFalse(state["allowed"])
        self.assertEqual(state["reason"], "missing_subscription")

    def test_empty_plan_modules_keep_existing_access_policy(self):
        plan = Abonnement.objects.create(nom="Ouvert", code="open", prix=10, duree_jours=30, modules_inclus=[])
        AbonnementEntreprise.objects.create(
            entreprise=self.entreprise_a,
            plan=plan,
            statut=AbonnementEntreprise.Statut.ACTIF,
            date_debut=date.today(),
            date_fin=date.today(),
            actif=True,
        )

        state = get_product_module_access_state(self.entreprise_a, "billing")

        self.assertTrue(state["allowed"])

    def test_plan_modules_can_restrict_module_access(self):
        plan = Abonnement.objects.create(
            nom="Clients only",
            code="clients-only",
            prix=10,
            duree_jours=30,
            modules_inclus=["clients"],
        )
        AbonnementEntreprise.objects.create(
            entreprise=self.entreprise_a,
            plan=plan,
            statut=AbonnementEntreprise.Statut.ACTIF,
            date_debut=date.today(),
            date_fin=date.today(),
            actif=True,
        )

        state = get_product_module_access_state(self.entreprise_a, "billing")

        self.assertFalse(state["allowed"])
        self.assertEqual(state["reason"], "module_not_in_plan")


class ExchangeRateServiceTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Devise")
        self.entreprise.devise = "CDF"
        self.entreprise.save(update_fields=["devise"])

    def test_same_currency_conversion_uses_rate_one(self):
        result = convert_amount(Decimal("10.00"), "USD", "USD")

        self.assertEqual(result.amount, Decimal("10.00"))
        self.assertEqual(result.rate, Decimal("1"))

    def test_conversion_uses_cached_rate(self):
        from django.utils import timezone

        ExchangeRate.objects.create(
            devise_source="USD",
            devise_cible="CDF",
            taux=Decimal("2750.00"),
            source_provider="manuel",
            date_taux=timezone.now(),
        )

        result = convert_amount(Decimal("10.00"), "USD", "CDF")

        self.assertEqual(result.amount, Decimal("27500.00"))
        self.assertEqual(result.rate, Decimal("2750.00"))

    def test_plan_price_is_unavailable_without_api_or_cached_rate(self):
        plan = Abonnement.objects.create(nom="Pro", code="pro-cdf", prix=10, duree_jours=30, actif=True)
        settings = PlatformSettings.get_solo()
        settings.devise_plateforme = "USD"
        settings.devise_defaut = "CDF"
        settings.exchange_rate_provider = "exchangerate_api"
        settings.save(update_fields=["devise_plateforme", "devise_defaut", "exchange_rate_provider"])
        ExchangeRate.objects.filter(devise_source="USD", devise_cible="CDF").delete()

        with patch(
            "core.services.exchange_rates.requests.get",
            side_effect=requests.RequestException("provider offline"),
        ) as mocked_get:
            price = get_plan_price_for_company(plan, self.entreprise)

        mocked_get.assert_called_once_with("https://open.er-api.com/v6/latest/USD", timeout=5)
        self.assertTrue(price["unavailable"])
        self.assertEqual(price["official_amount"], Decimal("10.00"))
        self.assertEqual(price["official_currency"], "USD")
        self.assertEqual(price["company_currency"], "CDF")
        self.assertIsNone(price["estimated_amount"])
        self.assertIsNone(price["rate"])

    def test_exchange_rate_provider_uses_dynamic_source_currency(self):
        pairs = [
            ("USD", "CDF", "2750"),
            ("USD", "EUR", "0.92"),
            ("EUR", "CDF", "3000"),
            ("USD", "XAF", "605"),
            ("USD", "AOA", "920"),
            ("CDF", "USD", "0.00036"),
        ]

        for source_currency, target_currency, rate in pairs:
            with self.subTest(source_currency=source_currency, target_currency=target_currency):
                ExchangeRate.objects.all().delete()
                response = Mock()
                response.status_code = 200
                response.json.return_value = {"result": "success", "rates": {target_currency: rate}}
                response.text = ""

                with patch("core.services.exchange_rates.requests.get", return_value=response) as mocked_get:
                    result = convert_amount(Decimal("1.00"), source_currency, target_currency)

                mocked_get.assert_called_once_with(
                    f"https://open.er-api.com/v6/latest/{source_currency}",
                    timeout=5,
                )
                self.assertEqual(result.rate, Decimal(rate))
                self.assertEqual(result.source_currency, source_currency)
                self.assertEqual(result.target_currency, target_currency)


class AuditLogTests(TestCase):
    def _create_default_plan(self, code):
        payload = next(plan for plan in get_default_paid_plans() if plan["code"] == code)
        return Abonnement.objects.create(**payload, actif=True)

    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Audit")
        self.entreprise_b = create_entreprise("Entreprise Audit B")
        self.gestionnaire = create_user("gestion-audit", "gestionnaire", self.entreprise)
        self.comptable = create_user("compta-audit", "comptable", self.entreprise)
        self.client_metier = create_client(self.entreprise, "Client Audit")
        self.premium_plan = self._create_default_plan("premium")
        activate_subscription_for_entreprise(
            entreprise=self.entreprise,
            plan=self.premium_plan,
            utilisateur=self.comptable,
        )

    def test_facture_creation_creates_audit_event_scoped_to_entreprise_and_user(self):
        facture = create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("100"))

        audit = ActivityLog.objects.get(action="facture_creee", objet_id=facture.id)
        self.assertEqual(audit.entreprise, self.entreprise)
        self.assertEqual(audit.utilisateur, self.gestionnaire)
        self.assertEqual(audit.module, "billing")
        self.assertEqual(audit.objet_type, "Facture")

    def test_payment_registration_creates_audit_event_without_breaking_workflow(self):
        facture = create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("100"))

        paiement = register_payment(
            facture=facture,
            montant=Decimal("20"),
            mode=PaiementFacture.ModePaiement.ESPECES,
            user=self.comptable,
            note="Acompte audit",
        )

        audit = ActivityLog.objects.get(action="facture_payee", objet_id=paiement.id)
        self.assertEqual(audit.entreprise, self.entreprise)
        self.assertEqual(audit.utilisateur, self.comptable)
        self.assertEqual(audit.module, "billing")
        self.assertEqual(paiement.montant, Decimal("20"))

    def test_client_creation_creates_audit_event(self):
        client = create_client_for_entreprise(
            entreprise=self.entreprise,
            nom="Client Journalise",
            telephone="+243111111111",
            email="journalise@example.com",
            utilisateur=self.gestionnaire,
        )

        audit = ActivityLog.objects.get(action="client_cree", objet_id=client.id)
        self.assertEqual(audit.entreprise, self.entreprise)
        self.assertEqual(audit.utilisateur, self.gestionnaire)
        self.assertEqual(audit.module, "clients")

    def test_audit_log_is_isolated_by_entreprise(self):
        client_b = create_client(self.entreprise_b, "Client B")
        user_b = create_user("gestion-audit-b", "gestionnaire", self.entreprise_b)
        create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("50"))
        create_facture_sample(self.entreprise_b, user_b, client_b, Decimal("70"))

        logs_a = ActivityLog.objects.filter(entreprise=self.entreprise)
        logs_b = ActivityLog.objects.filter(entreprise=self.entreprise_b)
        self.assertTrue(logs_a.exists())
        self.assertTrue(logs_b.exists())
        self.assertTrue(all(log.entreprise_id == self.entreprise.id for log in logs_a))
        self.assertTrue(all(log.entreprise_id == self.entreprise_b.id for log in logs_b))

    def test_audit_selectors_support_filters_and_desc_order(self):
        facture = create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("90"))
        register_payment(
            facture=facture,
            montant=Decimal("10"),
            mode=PaiementFacture.ModePaiement.ESPECES,
            user=self.comptable,
            note="Paiement filtre",
        )

        logs = list(get_activity_logs_by_entreprise(self.entreprise))
        self.assertGreaterEqual(len(logs), 2)
        self.assertGreaterEqual(logs[0].id, logs[-1].id)
        self.assertTrue(all(log.entreprise_id == self.entreprise.id for log in logs))

        billing_logs = list(get_activity_logs_by_entreprise(self.entreprise, module="billing"))
        self.assertTrue(all(log.module == "billing" for log in billing_logs))

        comptable_logs = list(get_activity_logs_by_entreprise(self.entreprise, utilisateur_id=self.comptable.id))
        self.assertTrue(all(log.utilisateur_id == self.comptable.id for log in comptable_logs))

        payment_logs = list(get_activity_logs_by_entreprise(self.entreprise, action="facture_payee"))
        self.assertTrue(all(log.action == "facture_payee" for log in payment_logs))

        role_logs = list(get_activity_logs_by_entreprise(self.entreprise, role="comptable"))
        self.assertTrue(role_logs)
        self.assertTrue(all(log.utilisateur and log.utilisateur.role == "comptable" for log in role_logs))

        dated_logs = list(
            get_activity_logs_by_entreprise(
                self.entreprise,
                date_from=logs[-1].date_creation.date(),
                date_to=logs[0].date_creation.date(),
            )
        )
        self.assertTrue(dated_logs)

    def test_audit_filter_options_are_scoped_to_entreprise(self):
        create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("30"))
        client_b = create_client(self.entreprise_b, "Client B")
        user_b = create_user("gestion-audit-b2", "gestionnaire", self.entreprise_b)
        create_facture_sample(self.entreprise_b, user_b, client_b, Decimal("40"))

        self.assertIn("billing", get_activity_modules_for_entreprise(self.entreprise))
        self.assertIn("facture_creee", get_activity_actions_for_entreprise(self.entreprise))
        users = list(get_activity_users_for_entreprise(self.entreprise))
        self.assertIn(self.gestionnaire, users)
        self.assertNotIn(user_b, users)
        role_values = [item["value"] for item in get_activity_roles_for_entreprise(self.entreprise)]
        self.assertIn("gestionnaire", role_values)
        self.assertNotIn("proprietaire", role_values)

    def test_activity_log_view_is_restricted_to_proprietaire_and_comptable_only(self):
        create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("100"))

        self.client.force_login(self.gestionnaire)
        forbidden = self.client.get(reverse("activity_log_list"))
        self.assertEqual(forbidden.status_code, 403)

        proprietaire = create_user("owner-audit", "proprietaire", self.entreprise)
        self.client.force_login(proprietaire)
        allowed = self.client.get(reverse("activity_log_list"))
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "Controle des flux")

        self.client.force_login(self.comptable)
        comptable_allowed = self.client.get(reverse("activity_log_list"))
        self.assertEqual(comptable_allowed.status_code, 200)
        self.assertContains(comptable_allowed, "Controle des flux")

    def test_activity_log_view_redirects_when_plan_does_not_include_audit(self):
        starter_company = create_entreprise("Starter Audit")
        starter_owner = create_user("owner-starter-audit", "proprietaire", starter_company)
        starter_plan = self._create_default_plan("starter")
        activate_subscription_for_entreprise(
            entreprise=starter_company,
            plan=starter_plan,
            utilisateur=starter_owner,
        )

        self.client.force_login(starter_owner)
        response = self.client.get(reverse("activity_log_list"))

        self.assertRedirects(response, reverse("abonnement_expire") + "?module=audit&reason=module_not_in_plan")

    def test_activity_log_view_filters_and_isolation_work(self):
        facture = create_facture_sample(self.entreprise, self.gestionnaire, self.client_metier, Decimal("100"))
        register_payment(
            facture=facture,
            montant=Decimal("10"),
            mode=PaiementFacture.ModePaiement.ESPECES,
            user=self.comptable,
            note="Paiement vue",
        )
        client_b = create_client(self.entreprise_b, "Client Vue B")
        owner_b = create_user("owner-audit-b", "proprietaire", self.entreprise_b)
        create_facture_sample(self.entreprise_b, owner_b, client_b, Decimal("50"))

        proprietaire = create_user("owner-audit-view", "proprietaire", self.entreprise)
        self.client.force_login(proprietaire)

        response = self.client.get(reverse("activity_log_list"))
        self.assertEqual(response.status_code, 200)
        logs = list(response.context["logs"])
        self.assertTrue(all(log.entreprise_id == self.entreprise.id for log in logs))

        filtered = self.client.get(
            reverse("activity_log_list"),
            {
                "action": "facture_payee",
                "utilisateur": self.comptable.id,
                "module": "billing",
                "role": "comptable",
                "date_from": logs[-1].date_creation.date().isoformat(),
                "date_to": logs[0].date_creation.date().isoformat(),
            },
        )
        self.assertEqual(filtered.status_code, 200)
        filtered_logs = list(filtered.context["logs"])
        self.assertTrue(filtered_logs)
        self.assertTrue(all(log.action == "facture_payee" for log in filtered_logs))
        self.assertTrue(all(log.utilisateur_id == self.comptable.id for log in filtered_logs))
        self.assertTrue(all(log.module == "billing" for log in filtered_logs))
        self.assertTrue(all(log.utilisateur and log.utilisateur.role == "comptable" for log in filtered_logs))

    def test_get_inscription_billing_history_returns_logs_in_desc_order(self):
        from joatham_apprenants.models import Apprenant, Formation, InscriptionFormation

        apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Audit", prenom="Eleve")
        formation = Formation.objects.create(entreprise=self.entreprise, nom="Excel", prix=Decimal("100.00"))
        inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise,
            apprenant=apprenant,
            formation=formation,
            montant_prevu=Decimal("100.00"),
        )

        ActivityLog.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.gestionnaire,
            action="facture_inscription_creee",
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=inscription.id,
            description="Facture creee.",
            metadata={"facture_numero": "F-0001"},
        )
        ActivityLog.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.gestionnaire,
            action="facture_deliee_inscription",
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=inscription.id,
            description="Facture deliee.",
            metadata={"facture_numero": "F-0001"},
        )

        history = get_inscription_billing_history(inscription)
        self.assertEqual([entry["action"] for entry in history], ["facture_deliee_inscription", "facture_inscription_creee"])

    def test_get_inscription_billing_history_handles_missing_metadata(self):
        from joatham_apprenants.models import Apprenant, Formation, InscriptionFormation

        apprenant = Apprenant.objects.create(entreprise=self.entreprise, nom="Audit 2", prenom="Eleve")
        formation = Formation.objects.create(entreprise=self.entreprise, nom="Word", prix=Decimal("150.00"))
        inscription = InscriptionFormation.objects.create(
            entreprise=self.entreprise,
            apprenant=apprenant,
            formation=formation,
            montant_prevu=Decimal("150.00"),
        )

        ActivityLog.objects.create(
            entreprise=self.entreprise,
            utilisateur=self.gestionnaire,
            action="facture_existante_liee_inscription",
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=inscription.id,
            description="Facture liee sans metadata complete.",
            metadata={},
        )
        ActivityLog.objects.create(
            entreprise=self.entreprise_b,
            utilisateur=None,
            action="facture_deliee_inscription",
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=inscription.id,
            description="Autre entreprise.",
            metadata={},
        )

        history = get_inscription_billing_history(inscription)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["facture_numero"], "")


class SuperAdminDashboardTests(TestCase):
    def setUp(self):
        self.plan_basic = Abonnement.objects.create(nom="Basic", code="basic", prix=10, duree_jours=30, actif=True)
        starter_payload = next(plan for plan in get_default_paid_plans() if plan["code"] == "starter")
        self.plan_starter = Abonnement.objects.create(**starter_payload, actif=True)
        self.plan_pro = Abonnement.objects.create(nom="Pro", code="pro", prix=30, duree_jours=30, actif=True)
        settings = PlatformSettings.get_solo()
        settings.mode_maintenance = False
        settings.maintenance_modules = []
        settings.maintenance_allowed_ips = ""
        settings.message_maintenance = "Maintenance"
        settings.save(update_fields=["mode_maintenance", "maintenance_modules", "maintenance_allowed_ips", "message_maintenance"])
        self.entreprise_a = create_entreprise("Entreprise Alpha")
        self.entreprise_b = create_entreprise("Entreprise Beta")
        self.owner = create_user("owner-super-test", "proprietaire", self.entreprise_a)
        self.super_admin = User.objects.create_user(
            username="superadmin",
            password="testpass123",
            role="super_admin",
            entreprise=None,
            email="superadmin@example.com",
        )
        AbonnementEntreprise.objects.create(
            entreprise=self.entreprise_a,
            plan=self.plan_basic,
            statut=AbonnementEntreprise.Statut.ESSAI,
            date_debut=date.today(),
            date_fin=date.today(),
            essai=True,
            actif=True,
        )
        AbonnementEntreprise.objects.create(
            entreprise=self.entreprise_b,
            plan=self.plan_pro,
            statut=AbonnementEntreprise.Statut.ACTIF,
            date_debut=date.today(),
            date_fin=date.today(),
            essai=False,
            actif=True,
        )
        create_user("manager-alpha", "gestionnaire", self.entreprise_a)
        create_user("accountant-alpha", "comptable", self.entreprise_a)

    def test_super_admin_dashboard_is_restricted_to_super_admin(self):
        self.client.force_login(self.owner)
        forbidden = self.client.get(reverse("super_admin_dashboard"))
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.super_admin)
        allowed = self.client.get(reverse("super_admin_dashboard"))
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "Super admin")
        self.assertContains(allowed, "Entreprise Alpha")
        self.assertContains(allowed, "Entreprise Beta")
        self.super_admin.refresh_from_db()
        self.assertIsNone(self.super_admin.entreprise_id)

    def test_super_admin_dashboard_shows_global_company_snapshot(self):
        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("super_admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["counts"]["total_entreprises"], 2)
        self.assertEqual(response.context["counts"]["essai"], 1)
        self.assertEqual(response.context["counts"]["actif"], 1)
        self.assertContains(response, "Basic")
        self.assertContains(response, "Pro")
        self.assertContains(response, "3")
        self.assertContains(response, "Administration SaaS")
        self.assertContains(response, "Paiements en attente")
        self.assertContains(response, "Entreprises")
        self.assertContains(response, "Points à surveiller")
        self.assertContains(response, "Espace Super Admin")
        self.assertContains(response, "Rechercher une entreprise")
        self.assertContains(response, "Statut abonnement")
        self.assertNotContains(response, reverse("super_admin_company_deactivate", args=[self.entreprise_a.id]))
        self.assertNotContains(response, "/super-admin/entreprises/%3Cid%3E/desactiver/")
        self.assertNotContains(response, "/super-admin/entreprises/<id>/desactiver/")

    def test_super_admin_navigation_uses_platform_entries_only(self):
        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("super_admin_dashboard"))

        labels = [item["label"] for item in response.context["dashboard_navigation"]]
        self.assertEqual(
            labels,
            [
                "Pilotage SaaS",
                "Entreprises",
                "Utilisateurs",
                "Abonnements",
                "Audit / logs",
                "Paramètres plateforme",
                "Taux de change",
                "Demandes SaaS",
            ],
        )
        self.assertNotIn("Factures", labels)
        self.assertNotIn("Services", labels)
        self.assertNotIn("Clients", labels)
        self.assertNotIn("Depenses", labels)
        self.assertNotIn("Comptabilite", labels)
        self.assertNotIn("Apprenants", labels)

        pilotage_item = next(item for item in response.context["dashboard_navigation"] if item["label"] == "Pilotage SaaS")
        company_item = next(item for item in response.context["dashboard_navigation"] if item["label"] == "Entreprises")
        subscription_item = next(item for item in response.context["dashboard_navigation"] if item["label"] == "Abonnements")
        users_item = next(item for item in response.context["dashboard_navigation"] if item["label"] == "Utilisateurs")
        audit_item = next(item for item in response.context["dashboard_navigation"] if item["label"] == "Audit / logs")
        settings_item = next(item for item in response.context["dashboard_navigation"] if item["label"] == "Paramètres plateforme")
        rates_item = next(item for item in response.context["dashboard_navigation"] if item["label"] == "Taux de change")
        messages_item = next(item for item in response.context["dashboard_navigation"] if item["label"] == "Demandes SaaS")

        self.assertEqual(pilotage_item["url"], "/super-admin/")
        self.assertEqual(company_item["url"], reverse("super_admin_company_list"))
        self.assertEqual(subscription_item["url"], reverse("super_admin_subscription_list"))
        self.assertEqual(users_item["url"], reverse("super_admin_user_list"))
        self.assertEqual(audit_item["url"], reverse("super_admin_audit_list"))
        self.assertEqual(settings_item["url"], reverse("super_admin_settings"))
        self.assertEqual(rates_item["url"], reverse("super_admin_exchange_rate_list"))
        self.assertEqual(messages_item["url"], reverse("super_admin_messages"))
        self.assertFalse(pilotage_item["is_disabled"])
        self.assertFalse(company_item["is_disabled"])
        self.assertFalse(subscription_item["is_disabled"])
        self.assertFalse(users_item["is_disabled"])
        self.assertFalse(audit_item["is_disabled"])
        self.assertFalse(settings_item["is_disabled"])
        self.assertFalse(rates_item["is_disabled"])
        self.assertFalse(messages_item["is_disabled"])

    def test_super_admin_company_list_shows_company_management_actions(self):
        self.client.force_login(self.super_admin)

        response = self.client.get(reverse("super_admin_company_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestion entreprises")
        self.assertContains(response, "Entreprise Alpha")
        self.assertContains(response, "Entreprise Beta")
        self.assertContains(response, "Active")
        self.assertContains(response, "Desactiver")
        self.assertContains(response, reverse("super_admin_company_deactivate", args=[self.entreprise_a.id]))
        self.assertNotContains(response, "/super-admin/entreprises/%3Cid%3E/desactiver/")
        self.assertNotContains(response, "/super-admin/entreprises/<id>/desactiver/")

    def test_super_admin_subscription_list_shows_subscription_management_actions(self):
        self.client.force_login(self.super_admin)

        response = self.client.get(reverse("super_admin_subscription_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Abonnements")
        self.assertContains(response, "Entreprise Alpha")
        self.assertContains(response, "Entreprise Beta")
        self.assertContains(response, "Date debut")
        self.assertContains(response, "Jours restants")
        self.assertContains(response, "Activer")
        self.assertContains(response, "Changer plan")
        self.assertContains(response, "Prolonger acces historique")
        self.assertContains(response, "Suspendre")

    def test_super_admin_can_manage_subscription_from_subscription_page(self):
        self.client.force_login(self.super_admin)

        response = self.client.post(
            reverse("super_admin_subscription_list"),
            {
                "action": "change_plan",
                "entreprise_id": self.entreprise_b.id,
                "plan_id": self.plan_starter.id,
            },
        )

        self.assertRedirects(response, reverse("super_admin_subscription_list"))
        subscription_b = AbonnementEntreprise.objects.get(entreprise=self.entreprise_b)
        self.assertEqual(subscription_b.plan, self.plan_starter)

    def test_super_admin_user_list_shows_users_and_safe_actions(self):
        self.client.force_login(self.super_admin)

        response = self.client.get(reverse("super_admin_user_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Utilisateurs")
        self.assertContains(response, self.super_admin.email)
        self.assertContains(response, self.owner.username)
        self.assertContains(response, "Compte courant")
        self.assertContains(response, "Desactiver")

    def test_super_admin_cannot_deactivate_self_from_user_list(self):
        self.client.force_login(self.super_admin)

        response = self.client.post(
            reverse("super_admin_user_list"),
            {
                "action": "deactivate_user",
                "user_id": self.super_admin.id,
            },
        )

        self.assertRedirects(response, reverse("super_admin_user_list"))
        self.super_admin.refresh_from_db()
        self.assertTrue(self.super_admin.is_active)

    def test_super_admin_can_deactivate_and_reactivate_tenant_user(self):
        self.client.force_login(self.super_admin)

        deactivate_response = self.client.post(
            reverse("super_admin_user_list"),
            {
                "action": "deactivate_user",
                "user_id": self.owner.id,
            },
        )
        self.assertRedirects(deactivate_response, reverse("super_admin_user_list"))
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)
        self.assertTrue(ActivityLog.objects.filter(entreprise=self.entreprise_a, action="utilisateur_desactive").exists())

        reactivate_response = self.client.post(
            reverse("super_admin_user_list"),
            {
                "action": "reactivate_user",
                "user_id": self.owner.id,
            },
        )
        self.assertRedirects(reactivate_response, reverse("super_admin_user_list"))
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertTrue(ActivityLog.objects.filter(entreprise=self.entreprise_a, action="utilisateur_reactive").exists())

    def test_super_admin_audit_list_shows_logs_and_filters(self):
        ActivityLog.objects.create(
            entreprise=self.entreprise_a,
            utilisateur=self.owner,
            action="test_audit_super_admin",
            module="tests",
            objet_type="User",
            objet_id=self.owner.id,
            description="Evenement audit visible super admin.",
        )
        self.client.force_login(self.super_admin)

        response = self.client.get(reverse("super_admin_audit_list"), {"module": "tests", "q": "visible"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Audit / logs")
        self.assertContains(response, "Evenement audit visible super admin.")
        self.assertContains(response, "Entreprise Alpha")
        self.assertContains(response, self.owner.username)
        self.assertContains(response, "test_audit_super_admin")
        self.assertContains(response, "Page")

    def test_super_admin_settings_page_updates_platform_settings(self):
        self.client.force_login(self.super_admin)

        response = self.client.post(
            reverse("super_admin_settings"),
            {
                "nom_plateforme": "JOATHAM Manager Pro",
                "email_systeme": "admin@joatham.com",
                "devise_defaut": "USD",
                "mode_maintenance": "on",
                "message_maintenance": "Maintenance planifiee ce soir.",
                "maintenance_allowed_ips": "127.0.0.1",
                "maintenance_modules": ["factures", "clients"],
            },
        )

        self.assertRedirects(response, reverse("super_admin_settings"))
        settings = PlatformSettings.get_solo()
        self.assertEqual(settings.nom_plateforme, "JOATHAM Manager Pro")
        self.assertEqual(settings.email_systeme, "admin@joatham.com")
        self.assertEqual(settings.devise_defaut, "USD")
        self.assertTrue(settings.mode_maintenance)
        self.assertEqual(settings.message_maintenance, "Maintenance planifiee ce soir.")
        self.assertEqual(settings.maintenance_allowed_ips, "127.0.0.1")
        self.assertEqual(settings.maintenance_modules, ["factures", "clients"])

    def test_super_admin_can_register_manual_subscription_payment(self):
        self.client.force_login(self.super_admin)

        response = self.client.post(
            reverse("super_admin_subscription_manual_payment", args=[self.entreprise_a.id]),
            {
                "plan": self.plan_pro.id,
                "montant": "50.00",
                "devise": "USD",
                "methode_paiement": PaiementAbonnement.Methode.CASH,
                "reference_paiement": "RECU-001",
                "periode_jours": 90,
            },
        )

        self.assertRedirects(response, reverse("super_admin_subscription_list"))
        paiement = PaiementAbonnement.objects.get(reference_paiement="RECU-001")
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.VALIDE)
        self.assertEqual(paiement.methode_paiement, PaiementAbonnement.Methode.CASH)
        self.assertEqual(paiement.periode_fin, date.today() + timedelta(days=90))

        subscription = self.entreprise_a.abonnement_entreprise
        subscription.refresh_from_db()
        self.assertEqual(subscription.plan, self.plan_pro)
        self.assertEqual(subscription.statut, AbonnementEntreprise.Statut.ACTIF)
        self.assertFalse(subscription.essai)
        self.assertEqual(subscription.date_fin, date.today() + timedelta(days=90))
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise_a,
                action="paiement_abonnement_enregistre",
                objet_id=paiement.id,
            ).exists()
        )

    def test_manual_subscription_payment_is_restricted_to_super_admin(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("super_admin_subscription_manual_payment", args=[self.entreprise_a.id]))

        self.assertEqual(response.status_code, 403)

    def test_company_can_request_paid_plan_without_auto_activation(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("subscription_plan_list"),
            {"plan_id": self.plan_pro.id},
        )

        self.assertRedirects(response, reverse("subscription_plan_list"))
        paiement = PaiementAbonnement.objects.get(
            entreprise=self.entreprise_a,
            plan=self.plan_pro,
            source_taux="demande_plan",
        )
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_ATTENTE)
        self.assertEqual(paiement.reference_paiement, "Demande plan Pro")

        subscription = self.entreprise_a.abonnement_entreprise
        subscription.refresh_from_db()
        self.assertEqual(subscription.plan, self.plan_basic)
        self.assertEqual(subscription.statut, AbonnementEntreprise.Statut.ESSAI)
        self.assertTrue(ActivityLog.objects.filter(action="abonnement_plan_demande", objet_id=paiement.id).exists())

    def test_subscription_plan_list_displays_available_conversion(self):
        from django.utils import timezone

        ExchangeRate.objects.create(
            devise_source="USD",
            devise_cible="CDF",
            taux=Decimal("2304.02457800"),
            source_provider="exchangerate_api",
            date_taux=timezone.now(),
        )
        self.entreprise_a.devise = "CDF"
        self.entreprise_a.save(update_fields=["devise"])
        self.client.force_login(self.owner)

        response = self.client.get(reverse("subscription_plan_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Estimation locale")
        self.assertContains(response, "Taux :")
        self.assertNotContains(response, "Conversion temporairement indisponible")

    def test_subscription_interfaces_do_not_offer_legacy_trial_plan(self):
        legacy_trial_plan = Abonnement.objects.create(
            nom="Plan d'essai",
            code="trial-default",
            prix=0,
            duree_jours=14,
            actif=True,
        )

        self.client.force_login(self.owner)
        plan_response = self.client.get(reverse("subscription_plan_list"))

        self.assertEqual(plan_response.status_code, 200)
        self.assertNotIn(legacy_trial_plan, list(plan_response.context["plans"]))
        self.assertNotContains(plan_response, "Plan d'essai")

        self.client.force_login(self.super_admin)
        admin_response = self.client.get(reverse("super_admin_subscription_list"))

        self.assertEqual(admin_response.status_code, 200)
        self.assertNotIn(legacy_trial_plan, list(admin_response.context["plans"]))
        self.assertNotContains(admin_response, "Plan d'essai")

    def test_super_admin_subscription_list_can_validate_plan_request(self):
        paiement = PaiementAbonnement.objects.create(
            entreprise=self.entreprise_a,
            plan=self.plan_pro,
            duree=PaiementAbonnement.Duree.MENSUEL,
            montant=Decimal("30.00"),
            montant_usd=Decimal("30.00"),
            devise_entreprise="USD",
            statut=PaiementAbonnement.Statut.EN_ATTENTE,
            reference_paiement="Demande plan Pro",
            source_taux="demande_plan",
        )
        self.client.force_login(self.super_admin)

        response = self.client.post(
            reverse("super_admin_subscription_list"),
            {
                "action": "validate_plan_request",
                "entreprise_id": self.entreprise_a.id,
            },
        )

        self.assertRedirects(response, reverse("super_admin_subscription_list"))
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.APPROUVEE)
        subscription = self.entreprise_a.abonnement_entreprise
        subscription.refresh_from_db()
        self.assertEqual(subscription.plan, self.plan_pro)
        self.assertEqual(subscription.statut, AbonnementEntreprise.Statut.ACTIF)
        self.assertFalse(subscription.essai)
        self.assertTrue(ActivityLog.objects.filter(action="abonnement_plan_demande_validee", objet_id=paiement.id).exists())

    def test_super_admin_subscription_list_shows_plan_request_actions(self):
        PaiementAbonnement.objects.create(
            entreprise=self.entreprise_a,
            plan=self.plan_pro,
            duree=PaiementAbonnement.Duree.MENSUEL,
            montant=Decimal("30.00"),
            montant_usd=Decimal("30.00"),
            devise_entreprise="USD",
            statut=PaiementAbonnement.Statut.EN_ATTENTE,
            reference_paiement="Demande plan Pro",
            source_taux="demande_plan",
        )
        self.client.force_login(self.super_admin)

        response = self.client.get(reverse("super_admin_subscription_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Plan demande : Pro")
        self.assertContains(response, 'value="validate_plan_request"')
        self.assertContains(response, 'value="refuse_plan_request"')
        self.assertNotContains(response, 'value="validate_payment"')

    def test_super_admin_subscription_list_can_refuse_plan_request_without_changing_plan(self):
        paiement = PaiementAbonnement.objects.create(
            entreprise=self.entreprise_a,
            plan=self.plan_pro,
            duree=PaiementAbonnement.Duree.MENSUEL,
            montant=Decimal("30.00"),
            montant_usd=Decimal("30.00"),
            devise_entreprise="USD",
            statut=PaiementAbonnement.Statut.EN_ATTENTE,
            reference_paiement="Demande plan Pro",
            source_taux="demande_plan",
        )
        self.client.force_login(self.super_admin)

        response = self.client.post(
            reverse("super_admin_subscription_list"),
            {
                "action": "refuse_plan_request",
                "entreprise_id": self.entreprise_a.id,
            },
        )

        self.assertRedirects(response, reverse("super_admin_subscription_list"))
        paiement.refresh_from_db()
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.REFUSE)
        subscription = self.entreprise_a.abonnement_entreprise
        subscription.refresh_from_db()
        self.assertEqual(subscription.plan, self.plan_basic)
        self.assertTrue(ActivityLog.objects.filter(action="abonnement_plan_demande_refusee", objet_id=paiement.id).exists())

    def test_super_admin_can_toggle_maintenance_without_required_currency(self):
        settings = PlatformSettings.get_solo()
        settings.nom_plateforme = "JOATHAM Stable"
        settings.email_systeme = "stable@joatham.com"
        settings.devise_defaut = "CDF"
        settings.mode_maintenance = False
        settings.message_maintenance = "Message stable"
        settings.maintenance_allowed_ips = "10.0.0.1"
        settings.save()
        self.client.force_login(self.super_admin)

        response = self.client.post(
            reverse("super_admin_settings"),
            {
                "mode_maintenance": "on",
            },
        )

        self.assertRedirects(response, reverse("super_admin_settings"))
        settings.refresh_from_db()
        self.assertEqual(settings.nom_plateforme, "JOATHAM Stable")
        self.assertEqual(settings.email_systeme, "stable@joatham.com")
        self.assertEqual(settings.devise_defaut, "CDF")
        self.assertEqual(settings.message_maintenance, "Message stable")
        self.assertEqual(settings.maintenance_allowed_ips, "10.0.0.1")
        self.assertTrue(settings.mode_maintenance)

    def test_platform_default_currency_is_only_used_when_company_currency_is_empty(self):
        settings = PlatformSettings.get_solo()
        settings.devise_defaut = "USD"
        settings.save(update_fields=["devise_defaut"])

        self.entreprise_a.devise = "AOA"
        self.entreprise_a.save(update_fields=["devise"])
        self.assertEqual(get_currency_code(self.entreprise_a), "AOA")

        self.entreprise_a.devise = ""
        self.entreprise_a.save(update_fields=["devise"])
        self.assertEqual(get_currency_code(self.entreprise_a), "USD")

    def test_maintenance_mode_blocks_tenant_users_but_not_super_admin(self):
        settings = PlatformSettings.get_solo()
        settings.mode_maintenance = True
        settings.message_maintenance = "Maintenance personnalisable"
        settings.save(update_fields=["mode_maintenance", "message_maintenance"])

        self.client.force_login(self.owner)
        blocked = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(blocked.status_code, 503)
        self.assertContains(blocked, "Maintenance personnalisable", status_code=503)

        manager = create_user("manager-maintenance", "gestionnaire", self.entreprise_a)
        self.client.force_login(manager)
        manager_blocked = self.client.get(reverse("gestion_dashboard"))
        self.assertEqual(manager_blocked.status_code, 503)

        self.client.force_login(self.super_admin)
        allowed = self.client.get(reverse("super_admin_settings"))
        self.assertEqual(allowed.status_code, 200)

    def test_maintenance_mode_allows_configured_ip(self):
        settings = PlatformSettings.get_solo()
        settings.mode_maintenance = True
        settings.maintenance_allowed_ips = "203.0.113.8, 198.51.100.9"
        settings.save(update_fields=["mode_maintenance", "maintenance_allowed_ips"])

        self.client.force_login(self.owner)
        response = self.client.get(reverse("admin_dashboard"), REMOTE_ADDR="203.0.113.8")

        self.assertNotEqual(response.status_code, 503)

    def test_module_maintenance_blocks_only_targeted_module(self):
        settings = PlatformSettings.get_solo()
        settings.mode_maintenance = False
        settings.maintenance_modules = ["factures"]
        settings.save(update_fields=["mode_maintenance", "maintenance_modules"])

        self.client.force_login(self.owner)
        blocked = self.client.get(reverse("facture_list"))
        self.assertEqual(blocked.status_code, 503)
        self.assertContains(blocked, "Le module Factures est momentanément en maintenance.", status_code=503)

        allowed = self.client.get(reverse("admin_dashboard"))
        self.assertNotEqual(allowed.status_code, 503)

    def test_module_maintenance_allows_configured_ip(self):
        settings = PlatformSettings.get_solo()
        settings.mode_maintenance = False
        settings.maintenance_modules = ["factures"]
        settings.maintenance_allowed_ips = "203.0.113.8"
        settings.save(update_fields=["mode_maintenance", "maintenance_modules", "maintenance_allowed_ips"])

        self.client.force_login(self.owner)
        response = self.client.get(reverse("facture_list"), REMOTE_ADDR="203.0.113.8")

        self.assertNotEqual(response.status_code, 503)

    def test_super_admin_dashboard_filters_companies_by_name_and_status(self):
        self.client.force_login(self.super_admin)

        search_response = self.client.get(reverse("super_admin_dashboard"), {"q": "Alpha"})
        self.assertEqual(search_response.status_code, 200)
        self.assertContains(search_response, "Entreprise Alpha")
        self.assertNotContains(search_response, "Entreprise Beta")

        status_response = self.client.get(reverse("super_admin_dashboard"), {"statut": "actif"})
        self.assertEqual(status_response.status_code, 200)
        self.assertContains(status_response, "Entreprise Beta")
        self.assertNotContains(status_response, "Entreprise Alpha")

    def test_super_admin_can_activate_suspend_extend_legacy_trial_and_change_plan(self):
        self.client.force_login(self.super_admin)

        activate_response = self.client.post(
            reverse("super_admin_dashboard"),
            {
                "action": "activate",
                "entreprise_id": self.entreprise_a.id,
                "plan_id": self.plan_pro.id,
            },
        )
        self.assertRedirects(activate_response, reverse("super_admin_dashboard"))
        subscription_a = AbonnementEntreprise.objects.get(entreprise=self.entreprise_a)
        self.assertEqual(subscription_a.statut, AbonnementEntreprise.Statut.ACTIF)
        self.assertEqual(subscription_a.plan, self.plan_pro)

        suspend_response = self.client.post(
            reverse("super_admin_dashboard"),
            {
                "action": "suspend",
                "entreprise_id": self.entreprise_b.id,
            },
        )
        self.assertRedirects(suspend_response, reverse("super_admin_dashboard"))
        subscription_b = AbonnementEntreprise.objects.get(entreprise=self.entreprise_b)
        self.assertEqual(subscription_b.statut, AbonnementEntreprise.Statut.SUSPENDU)

        change_plan_response = self.client.post(
            reverse("super_admin_dashboard"),
            {
                "action": "change_plan",
                "entreprise_id": self.entreprise_b.id,
                "plan_id": self.plan_starter.id,
            },
        )
        self.assertRedirects(change_plan_response, reverse("super_admin_dashboard"))
        subscription_b.refresh_from_db()
        self.assertEqual(subscription_b.plan, self.plan_starter)

        legacy_entreprise = create_entreprise("Entreprise Legacy Trial")
        legacy_subscription = AbonnementEntreprise.objects.create(
            entreprise=legacy_entreprise,
            plan=self.plan_basic,
            statut=AbonnementEntreprise.Statut.ESSAI,
            date_debut=date.today(),
            date_fin=date.today() + timedelta(days=7),
            essai=True,
            actif=True,
        )
        previous_end = legacy_subscription.date_fin
        extend_response = self.client.post(
            reverse("super_admin_dashboard"),
            {
                "action": "extend_trial",
                "entreprise_id": legacy_entreprise.id,
                "trial_days": 7,
                "plan_id": self.plan_starter.id,
            },
        )
        self.assertRedirects(extend_response, reverse("super_admin_dashboard"))
        legacy_subscription.refresh_from_db()
        self.assertEqual(legacy_subscription.statut, AbonnementEntreprise.Statut.ESSAI)
        self.assertEqual(legacy_subscription.plan, self.plan_starter)
        self.assertGreater(legacy_subscription.date_fin, previous_end)

        blocked_extend_response = self.client.post(
            reverse("super_admin_dashboard"),
            {
                "action": "extend_trial",
                "entreprise_id": self.entreprise_b.id,
                "trial_days": 7,
                "plan_id": self.plan_starter.id,
            },
        )
        self.assertRedirects(blocked_extend_response, reverse("super_admin_dashboard"))
        subscription_b.refresh_from_db()
        self.assertNotEqual(subscription_b.statut, AbonnementEntreprise.Statut.ESSAI)

    def test_super_admin_company_deactivation_requires_exact_name_confirmation(self):
        self.client.force_login(self.super_admin)

        response = self.client.post(
            reverse("super_admin_company_deactivate", args=[self.entreprise_a.id]),
            {"confirmation_name": "Entreprise alpha"},
        )

        self.assertEqual(response.status_code, 200)
        self.entreprise_a.refresh_from_db()
        self.assertTrue(self.entreprise_a.is_active)
        self.assertContains(response, "ne correspond pas exactement")

    def test_super_admin_can_deactivate_company_without_deleting_data(self):
        self.client.force_login(self.super_admin)

        response = self.client.post(
            reverse("super_admin_company_deactivate", args=[self.entreprise_a.id]),
            {"confirmation_name": self.entreprise_a.nom},
        )

        self.assertRedirects(response, reverse("super_admin_company_list"))
        self.entreprise_a.refresh_from_db()
        self.assertFalse(self.entreprise_a.is_active)
        self.assertTrue(User.objects.filter(entreprise=self.entreprise_a).exists())
        self.assertFalse(User.objects.filter(entreprise=self.entreprise_a, is_active=True).exists())
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise_a,
                action="entreprise_desactivee",
                module="super_admin",
                objet_type="Entreprise",
                objet_id=self.entreprise_a.id,
            ).exists()
        )

        dashboard = self.client.get(reverse("super_admin_dashboard"))
        self.assertNotContains(dashboard, "Entreprise Alpha")
        self.assertContains(dashboard, "Entreprise Beta")

        company_list = self.client.get(reverse("super_admin_company_list"), {"status": "inactive"})
        self.assertContains(company_list, "Entreprise Alpha")
        self.assertContains(company_list, "Desactivee")

    def test_inactive_company_user_cannot_access_platform(self):
        self.entreprise_a.is_active = False
        self.entreprise_a.save(update_fields=["is_active"])
        self.client.force_login(self.owner)

        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 403)


class SubscriptionPaymentTests(TestCase):
    def setUp(self):
        self.plan_basic = Abonnement.objects.create(nom="Starter", code="starter", prix=10, duree_jours=30, actif=True)
        self.plan_pro = Abonnement.objects.create(nom="Pro", code="pro", prix=30, duree_jours=30, actif=True)
        settings = PlatformSettings.get_solo()
        settings.mode_maintenance = False
        settings.maintenance_modules = []
        settings.maintenance_allowed_ips = ""
        settings.message_maintenance = "Maintenance"
        settings.save(update_fields=["mode_maintenance", "maintenance_modules", "maintenance_allowed_ips", "message_maintenance"])
        self.entreprise = create_entreprise("Entreprise Paiement")
        self.owner = create_user("owner-payment", "proprietaire", self.entreprise)
        self.super_admin = User.objects.create_user(
            username="superadmin-payment",
            password="testpass123",
            role="super_admin",
            entreprise=None,
            email="superadmin-payment@example.com",
        )

    def _complete_cinetpay_settings(self, **overrides):
        config = {
            "JOATHAM_AUTO_PAYMENT_ENABLED": True,
            "JOATHAM_PAYMENT_PROVIDER": "cinetpay",
            "JOATHAM_PAYMENT_PUBLIC_KEY": "",
            "JOATHAM_PAYMENT_SECRET_KEY": "",
            "JOATHAM_PAYMENT_WEBHOOK_SECRET": "",
            "JOATHAM_PAYMENT_CURRENCY": "",
            "JOATHAM_PAYMENT_CALLBACK_URL": "https://app.example.com/abonnement/webhooks/cinetpay/",
            "JOATHAM_PAYMENT_RETURN_URL": "https://app.example.com/abonnement/paiement/retour/",
            "JOATHAM_PAYMENT_CHANNELS": "",
            "JOATHAM_PAYMENT_SANDBOX": True,
            "JOATHAM_PAYMENT_HTTP_TIMEOUT": 20.0,
            "CINETPAY_SITE_ID": "site-123",
            "CINETPAY_APIKEY": "api-key",
            "CINETPAY_SECRET_KEY": "secret-key",
            "CINETPAY_CURRENCY": "USD",
            "CINETPAY_CHANNELS": "MOBILE_MONEY",
            "CINETPAY_PAYMENT_URL": "https://api-checkout.cinetpay.com/v2/payment",
            "CINETPAY_PAYMENT_CHECK_URL": "https://api-checkout.cinetpay.com/v2/payment/check",
        }
        config.update(overrides)
        return config

    def _assert_cinetpay_checkout_creation_fails_safely(self, expected_message):
        with self.assertRaisesMessage(PaymentProviderError, expected_message) as ctx:
            create_automatic_subscription_payment_request(
                entreprise=self.entreprise,
                plan=self.plan_basic,
                duree=PaiementAbonnement.Duree.MENSUEL,
                provider="cinetpay",
                utilisateur=self.owner,
            )
        error_text = str(ctx.exception)
        for hidden_value in ("api-key", "secret-key", "webhook-secret"):
            self.assertNotIn(hidden_value, error_text)
        self.assertFalse(PaiementAbonnement.objects.filter(entreprise=self.entreprise, provider="cinetpay").exists())

    def test_owner_can_create_subscription_payment_request_without_activation(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("subscription_payment_create"),
            {
                "plan": self.plan_basic.id,
                "duree": PaiementAbonnement.Duree.TRIMESTRIEL,
                "telephone_paiement": "+243970258117",
                "reference_paiement": "MOMO-123",
            },
        )

        self.assertRedirects(response, reverse("subscription_overview"))
        paiement = PaiementAbonnement.objects.get(entreprise=self.entreprise)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_ATTENTE)
        self.assertEqual(paiement.montant, Decimal("30"))
        self.assertEqual(paiement.montant_usd, Decimal("30"))
        self.assertEqual(paiement.devise_entreprise, self.entreprise.devise)
        self.assertTrue(paiement.taux_change_reference)
        self.assertEqual(paiement.telephone_paiement, "+243970258117")
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    def test_subscription_price_rules_match_v1_periods(self):
        self.assertEqual(get_subscription_price_usd(plan=self.plan_basic, duree=PaiementAbonnement.Duree.MENSUEL), Decimal("10"))
        self.assertEqual(get_subscription_price_usd(plan=self.plan_basic, duree=PaiementAbonnement.Duree.TRIMESTRIEL), Decimal("30"))
        self.assertEqual(get_subscription_price_usd(plan=self.plan_basic, duree=PaiementAbonnement.Duree.ANNUEL), Decimal("120"))

    def test_subscription_payment_estimate_uses_usd_reference_and_local_snapshot(self):
        from django.utils import timezone

        settings = PlatformSettings.get_solo()
        settings.devise_plateforme = "USD"
        settings.save(update_fields=["devise_plateforme"])
        self.entreprise.devise = "CDF"
        self.entreprise.save(update_fields=["devise"])
        ExchangeRate.objects.create(
            devise_source="USD",
            devise_cible="CDF",
            taux=Decimal("2300.00"),
            source_provider="test_cached_rate",
            date_taux=timezone.now(),
        )

        estimate = build_subscription_payment_estimate(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
        )

        self.assertEqual(estimate["amount_usd"], Decimal("10.00"))
        self.assertEqual(estimate["currency_code"], self.entreprise.devise)
        self.assertEqual(estimate["estimated_amount"], Decimal("23000.00"))
        self.assertEqual(estimate["exchange_rate"], Decimal("2300.00"))
        self.assertEqual(estimate["exchange_source"], "test_cached_rate")

    def test_payment_form_displays_whatsapp_and_price_previews(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("subscription_payment_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Montant de référence")
        self.assertContains(response, "Montant estimatif dans votre devise")
        self.assertContains(response, "Contacter via WhatsApp")
        self.assertContains(response, "243970258117")

    def test_subscription_overview_shows_actions_without_auto_payment_provider(self):
        create_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            reference_paiement="MOMO-PENDING-ACTION",
            utilisateur=self.owner,
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("subscription_overview"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Voir les plans")
        self.assertContains(response, "Demandes / paiements en cours : 1")
        self.assertContains(response, "Paiement automatique bientôt disponible")
        self.assertNotContains(response, "Payer automatiquement")

    def test_subscription_plan_list_keeps_manual_request_and_hides_active_auto_payment(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("subscription_plan_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choisir ce pack")
        self.assertContains(response, "Paiement CinetPay non configuré")
        self.assertNotContains(response, "Payer avec CinetPay")

    def test_automatic_payment_start_is_rejected_without_configured_provider(self):
        self.client.force_login(self.owner)

        response = self.client.post(reverse("subscription_payment_automatic_start", args=[self.plan_basic.id]))

        self.assertRedirects(response, reverse("subscription_plan_list"))
        self.assertFalse(
            PaiementAbonnement.objects.filter(
                entreprise=self.entreprise,
                methode_paiement=PaiementAbonnement.Methode.AUTOMATIQUE,
            ).exists()
        )
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        DEBUG=True,
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="test",
        JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True,
        JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret",
    )
    def test_automatic_payment_start_uses_test_provider_only_when_enabled_in_debug(self):
        self.client.force_login(self.owner)

        response = self.client.post(reverse("subscription_payment_automatic_start", args=[self.plan_basic.id]))
        paiement = PaiementAbonnement.objects.get(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            methode_paiement=PaiementAbonnement.Methode.AUTOMATIQUE,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], paiement.checkout_url)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_ATTENTE)
        self.assertEqual(paiement.provider, "test")
        self.assertIn(paiement.external_reference, paiement.checkout_url)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="",
        CINETPAY_APIKEY="",
        CINETPAY_SECRET_KEY="",
        JOATHAM_PAYMENT_CALLBACK_URL="",
        JOATHAM_PAYMENT_RETURN_URL="",
    )
    def test_cinetpay_incomplete_config_keeps_auto_payment_unavailable(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("subscription_plan_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paiement CinetPay non configuré")
        self.assertNotContains(response, "Payer avec CinetPay")

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="",
        CINETPAY_APIKEY="",
        CINETPAY_SECRET_KEY="",
        JOATHAM_PAYMENT_CALLBACK_URL="",
        JOATHAM_PAYMENT_RETURN_URL="",
    )
    def test_cinetpay_incomplete_config_rejects_automatic_payment_start(self):
        self.client.force_login(self.owner)

        response = self.client.post(reverse("subscription_payment_automatic_start", args=[self.plan_basic.id]))

        self.assertRedirects(response, reverse("subscription_plan_list"))
        self.assertFalse(
            PaiementAbonnement.objects.filter(
                entreprise=self.entreprise,
                methode_paiement=PaiementAbonnement.Methode.AUTOMATIQUE,
            ).exists()
        )
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        CINETPAY_CURRENCY="USD",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
    )
    def test_cinetpay_configured_shows_auto_payment_action(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("subscription_plan_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choisir ce pack")
        self.assertContains(response, "Payer avec CinetPay")
        self.assertNotContains(response, "Paiement CinetPay non configuré")

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        CINETPAY_CURRENCY="",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
    )
    def test_cinetpay_missing_currency_keeps_auto_payment_unavailable(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("subscription_plan_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paiement CinetPay non configuré")
        self.assertNotContains(response, "Payer avec CinetPay")

    def test_cinetpay_diagnostic_reports_disabled_auto_payment(self):
        with override_settings(**self._complete_cinetpay_settings(JOATHAM_AUTO_PAYMENT_ENABLED=False)):
            diagnostic = get_automatic_payment_configuration_diagnostic()

        self.assertFalse(diagnostic["enabled"])
        self.assertEqual(diagnostic["provider"], "cinetpay")
        self.assertTrue(diagnostic["provider_is_cinetpay"])
        self.assertFalse(diagnostic["configured"])
        self.assertEqual(diagnostic["missing_required_settings"], [])
        self.assertIn("Paiement automatique desactive.", diagnostic["warnings"])

    def test_cinetpay_diagnostic_reports_non_cinetpay_provider(self):
        with override_settings(**self._complete_cinetpay_settings(JOATHAM_PAYMENT_PROVIDER="manual")):
            diagnostic = get_automatic_payment_configuration_diagnostic()

        self.assertTrue(diagnostic["enabled"])
        self.assertEqual(diagnostic["provider"], "manual")
        self.assertFalse(diagnostic["provider_is_cinetpay"])
        self.assertFalse(diagnostic["configured"])
        self.assertIn("Provider actif different de CinetPay.", diagnostic["warnings"])

    def test_cinetpay_diagnostic_reports_missing_required_settings(self):
        missing_cases = (
            ("CINETPAY_SITE_ID", {"CINETPAY_SITE_ID": "", "JOATHAM_PAYMENT_PUBLIC_KEY": ""}),
            ("CINETPAY_APIKEY", {"CINETPAY_APIKEY": "", "JOATHAM_PAYMENT_SECRET_KEY": ""}),
            ("CINETPAY_SECRET_KEY", {"CINETPAY_SECRET_KEY": "", "JOATHAM_PAYMENT_WEBHOOK_SECRET": ""}),
            ("CINETPAY_CURRENCY", {"CINETPAY_CURRENCY": "", "JOATHAM_PAYMENT_CURRENCY": ""}),
            ("JOATHAM_PAYMENT_CALLBACK_URL", {"JOATHAM_PAYMENT_CALLBACK_URL": ""}),
            ("JOATHAM_PAYMENT_RETURN_URL", {"JOATHAM_PAYMENT_RETURN_URL": ""}),
        )

        for missing_setting, overrides in missing_cases:
            with self.subTest(missing_setting=missing_setting):
                with override_settings(**self._complete_cinetpay_settings(**overrides)):
                    diagnostic = get_automatic_payment_configuration_diagnostic()

                self.assertFalse(diagnostic["configured"])
                self.assertIn(missing_setting, diagnostic["missing_required_settings"])
                self.assertNotIn(missing_setting, diagnostic["present_required_settings"])
                self.assertIn("Configuration CinetPay incomplete.", diagnostic["warnings"])

    def test_cinetpay_diagnostic_reports_complete_configuration_without_secret_values(self):
        with override_settings(**self._complete_cinetpay_settings()):
            diagnostic = get_automatic_payment_configuration_diagnostic()

        self.assertTrue(diagnostic["enabled"])
        self.assertEqual(diagnostic["provider"], "cinetpay")
        self.assertTrue(diagnostic["provider_is_cinetpay"])
        self.assertTrue(diagnostic["configured"])
        self.assertEqual(diagnostic["missing_required_settings"], [])
        self.assertIn("CINETPAY_SITE_ID", diagnostic["present_required_settings"])
        self.assertIn("CINETPAY_APIKEY", diagnostic["present_required_settings"])
        self.assertIn("CINETPAY_SECRET_KEY", diagnostic["present_required_settings"])
        self.assertEqual(diagnostic["payment_environment"], "Sandbox")
        self.assertEqual(diagnostic["payment_url_source"], "default")
        self.assertEqual(diagnostic["check_url_source"], "default")
        self.assertEqual(diagnostic["payment_url_source_label"], "URL par défaut")
        self.assertEqual(diagnostic["check_url_source_label"], "URL par défaut")
        self.assertTrue(diagnostic["sandbox_flag"])
        self.assertIn("URLs CinetPay par défaut utilisées ; confirmez leur environnement avant activation réelle.", diagnostic["warnings"])

        diagnostic_text = repr(diagnostic)
        for hidden_value in (
            "site-123",
            "api-key",
            "secret-key",
            "https://app.example.com/abonnement/webhooks/cinetpay/",
            "https://app.example.com/abonnement/paiement/retour/",
        ):
            self.assertNotIn(hidden_value, diagnostic_text)

    def test_cinetpay_diagnostic_reports_production_environment(self):
        with override_settings(**self._complete_cinetpay_settings(JOATHAM_PAYMENT_SANDBOX=False)):
            diagnostic = get_automatic_payment_configuration_diagnostic()

        self.assertEqual(diagnostic["payment_environment"], "Production")
        self.assertFalse(diagnostic["sandbox_flag"])
        self.assertTrue(diagnostic["configured"])

    def test_cinetpay_diagnostic_reports_non_configured_environment(self):
        with override_settings(**self._complete_cinetpay_settings(JOATHAM_AUTO_PAYMENT_ENABLED=False, JOATHAM_PAYMENT_PROVIDER="")):
            diagnostic = get_automatic_payment_configuration_diagnostic()

        self.assertEqual(diagnostic["payment_environment"], "Non configuré")
        self.assertFalse(diagnostic["configured"])
        self.assertIn("Paiement automatique desactive.", diagnostic["warnings"])
        self.assertIn("Provider de paiement non renseigne.", diagnostic["warnings"])

    def test_cinetpay_diagnostic_reports_custom_urls_without_query_secret(self):
        with override_settings(
            **self._complete_cinetpay_settings(
                CINETPAY_PAYMENT_URL="https://sandbox.cinetpay.example/v2/payment?apikey=secret-url-token",
                CINETPAY_PAYMENT_CHECK_URL="https://sandbox.cinetpay.example/v2/payment/check?token=secret-check-token",
            )
        ):
            diagnostic = get_automatic_payment_configuration_diagnostic()

        self.assertEqual(diagnostic["payment_url_source"], "custom")
        self.assertEqual(diagnostic["check_url_source"], "custom")
        self.assertEqual(diagnostic["payment_url_source_label"], "URL personnalisée")
        self.assertEqual(diagnostic["check_url_source_label"], "URL personnalisée")
        self.assertEqual(diagnostic["payment_url"], "https://sandbox.cinetpay.example/v2/payment")
        self.assertEqual(diagnostic["check_url"], "https://sandbox.cinetpay.example/v2/payment/check")
        diagnostic_text = repr(diagnostic)
        self.assertNotIn("secret-url-token", diagnostic_text)
        self.assertNotIn("secret-check-token", diagnostic_text)

    def test_cinetpay_diagnostic_warns_when_sandbox_uses_custom_production_url(self):
        with override_settings(
            **self._complete_cinetpay_settings(
                JOATHAM_PAYMENT_SANDBOX=True,
                CINETPAY_PAYMENT_URL="https://secure.cinetpay.com/v2/payment",
                CINETPAY_PAYMENT_CHECK_URL="https://secure.cinetpay.com/v2/payment/check",
            )
        ):
            diagnostic = get_automatic_payment_configuration_diagnostic()

        self.assertEqual(diagnostic["payment_environment"], "Sandbox")
        self.assertIn("Mode sandbox actif avec URL CinetPay de production personnalisée.", diagnostic["warnings"])

    def test_cinetpay_diagnostic_warns_when_production_uses_custom_sandbox_url(self):
        with override_settings(
            **self._complete_cinetpay_settings(
                JOATHAM_PAYMENT_SANDBOX=False,
                CINETPAY_PAYMENT_URL="https://sandbox.cinetpay.example/v2/payment",
                CINETPAY_PAYMENT_CHECK_URL="https://sandbox.cinetpay.example/v2/payment/check",
            )
        ):
            diagnostic = get_automatic_payment_configuration_diagnostic()

        self.assertEqual(diagnostic["payment_environment"], "Production")
        self.assertIn("Mode production actif avec URL CinetPay sandbox personnalisée.", diagnostic["warnings"])

    def test_cinetpay_diagnostic_warns_when_environment_is_ambiguous(self):
        with override_settings(**self._complete_cinetpay_settings(JOATHAM_PAYMENT_SANDBOX=None)):
            diagnostic = get_automatic_payment_configuration_diagnostic()

        self.assertEqual(diagnostic["payment_environment"], "Ambigu")
        self.assertIn("Environnement CinetPay ambigu : vérifiez JOATHAM_PAYMENT_SANDBOX et le provider.", diagnostic["warnings"])

    def test_super_admin_settings_shows_safe_cinetpay_diagnostic(self):
        self.client.force_login(self.super_admin)

        with override_settings(**self._complete_cinetpay_settings(CINETPAY_APIKEY="", JOATHAM_PAYMENT_SECRET_KEY="")):
            response = self.client.get(reverse("super_admin_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Diagnostic CinetPay")
        self.assertContains(response, "CINETPAY_APIKEY")
        self.assertContains(response, "Configuration CinetPay incomplete")
        self.assertContains(response, "Environnement paiement")
        self.assertContains(response, "URL par défaut")
        self.assertContains(response, "Alertes de cohérence")
        self.assertNotContains(response, "site-123")
        self.assertNotContains(response, "api-key")
        self.assertNotContains(response, "secret-key")
        self.assertNotContains(response, "https://app.example.com/abonnement/webhooks/cinetpay/")
        self.assertNotContains(response, "https://app.example.com/abonnement/paiement/retour/")

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        CINETPAY_API_PASSWORD="api-password-not-used-by-checkout-v2",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
        CINETPAY_CHANNELS="MOBILE_MONEY",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_create_payment_sends_expected_payload_and_stores_checkout_url(self, post_mock):
        post_mock.return_value = self._cinetpay_http_response(
            {
                "code": "201",
                "message": "CREATED",
                "data": {
                    "payment_token": "payment-token-1",
                    "payment_url": "https://checkout.cinetpay.com/payment/payment-token-1",
                },
                "api_response_id": "api-init-1",
            }
        )
        self.client.force_login(self.owner)

        response = self.client.post(reverse("subscription_payment_automatic_start", args=[self.plan_basic.id]))
        paiement = PaiementAbonnement.objects.get(
            entreprise=self.entreprise,
            methode_paiement=PaiementAbonnement.Methode.AUTOMATIQUE,
        )
        payload = post_mock.call_args.kwargs["json"]

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], paiement.checkout_url)
        self.assertEqual(payload["apikey"], "api-key")
        self.assertEqual(payload["site_id"], "site-123")
        self.assertEqual(payload["transaction_id"], paiement.external_reference)
        self.assertEqual(payload["amount"], 10)
        self.assertEqual(payload["currency"], "USD")
        self.assertEqual(payload["notify_url"], "https://app.example.com/abonnement/webhooks/cinetpay/")
        self.assertIn(paiement.external_reference, payload["return_url"])
        self.assertEqual(payload["channels"], "MOBILE_MONEY")
        self.assertNotIn("password", payload)
        self.assertNotIn("api_password", payload)
        self.assertEqual(paiement.checkout_url, "https://checkout.cinetpay.com/payment/payment-token-1")
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="CDF",
        CINETPAY_CHANNELS="MOBILE_MONEY",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_cdf_currency_uses_converted_expected_amount(self, post_mock):
        from django.utils import timezone

        ExchangeRate.objects.create(
            devise_source="USD",
            devise_cible="CDF",
            taux=Decimal("2300.00"),
            source_provider="test_cached_rate",
            date_taux=timezone.now(),
        )
        self.entreprise.devise = "CDF"
        self.entreprise.save(update_fields=["devise"])
        post_mock.return_value = self._cinetpay_http_response(
            {
                "code": "201",
                "message": "CREATED",
                "data": {
                    "payment_token": "payment-token-cdf",
                    "payment_url": "https://checkout.cinetpay.com/payment/payment-token-cdf",
                },
                "api_response_id": "api-init-cdf",
            }
        )
        self.client.force_login(self.owner)

        response = self.client.post(reverse("subscription_payment_automatic_start", args=[self.plan_basic.id]))
        paiement = PaiementAbonnement.objects.get(
            entreprise=self.entreprise,
            methode_paiement=PaiementAbonnement.Methode.AUTOMATIQUE,
        )
        payload = post_mock.call_args.kwargs["json"]

        self.assertEqual(response.status_code, 302)
        self.assertEqual(payload["currency"], "CDF")
        self.assertEqual(payload["amount"], 23000)
        self.assertEqual(paiement.amount_expected, Decimal("23000.00"))
        self.assertEqual(paiement.montant_usd, Decimal("10.00"))
        self.assertEqual(paiement.paid_currency, "CDF")

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_checkout_network_error_is_safe_and_rolls_back_payment(self, post_mock):
        post_mock.side_effect = requests.ConnectionError("api-key secret-key network detail")

        self._assert_cinetpay_checkout_creation_fails_safely("CinetPay est temporairement indisponible.")

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_checkout_error_message_does_not_expose_secret(self, post_mock):
        post_mock.side_effect = requests.ConnectionError("api-key secret-key network detail")
        self.client.force_login(self.owner)

        response = self.client.post(reverse("subscription_payment_automatic_start", args=[self.plan_basic.id]), follow=True)
        content = response.content.decode("utf-8")

        self.assertContains(response, "CinetPay est temporairement indisponible.")
        self.assertNotIn("api-key", content)
        self.assertNotIn("secret-key", content)
        self.assertFalse(PaiementAbonnement.objects.filter(entreprise=self.entreprise, provider="cinetpay").exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_checkout_timeout_is_safe_and_rolls_back_payment(self, post_mock):
        post_mock.side_effect = requests.Timeout("secret-key timeout detail")

        self._assert_cinetpay_checkout_creation_fails_safely("CinetPay est temporairement indisponible.")

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_checkout_invalid_json_is_safe_and_rolls_back_payment(self, post_mock):
        response = Mock()
        response.status_code = 200
        response.json.side_effect = ValueError("api-key json detail")
        post_mock.return_value = response

        self._assert_cinetpay_checkout_creation_fails_safely("Reponse CinetPay invalide.")

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_checkout_without_checkout_url_is_safe_and_rolls_back_payment(self, post_mock):
        post_mock.return_value = self._cinetpay_http_response({"code": "201", "message": "CREATED", "data": {}})

        self._assert_cinetpay_checkout_creation_fails_safely("CinetPay n'a pas retourne d'URL de paiement.")

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    def test_cinetpay_webhook_without_transaction_id_is_rejected(self):
        paiement = self._create_cinetpay_payment()

        response = self.client.post(
            reverse("subscription_payment_webhook", kwargs={"provider": "cinetpay"}),
            data={"cpm_site_id": "site-123"},
        )
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_ATTENTE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    def test_cinetpay_webhook_with_wrong_hmac_is_rejected(self):
        paiement = self._create_cinetpay_payment()
        payload = self._cinetpay_notification_payload(paiement)

        response = self.client.post(
            reverse("subscription_payment_webhook", kwargs={"provider": "cinetpay"}),
            data=payload,
            HTTP_X_TOKEN="wrong-token",
        )
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_ATTENTE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_payment_check_network_error_is_safe(self, post_mock):
        paiement = self._create_cinetpay_payment()
        post_mock.side_effect = requests.ConnectionError("api-key secret-key check detail")

        response = self._post_cinetpay_webhook(paiement)
        paiement.refresh_from_db()
        payload = json.loads(response.content.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["detail"], "CinetPay est temporairement indisponible.")
        self.assertNotIn("api-key", response.content.decode("utf-8"))
        self.assertNotIn("secret-key", response.content.decode("utf-8"))
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_ATTENTE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_payment_check_invalid_json_is_safe(self, post_mock):
        paiement = self._create_cinetpay_payment()
        response_mock = Mock()
        response_mock.status_code = 200
        response_mock.json.side_effect = ValueError("secret-key check json detail")
        post_mock.return_value = response_mock

        response = self._post_cinetpay_webhook(paiement)
        paiement.refresh_from_db()
        payload = json.loads(response.content.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["detail"], "Reponse CinetPay invalide.")
        self.assertNotIn("secret-key", response.content.decode("utf-8"))
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_ATTENTE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_accepted_webhook_activates_subscription_after_verification(self, post_mock):
        paiement = self._create_cinetpay_payment()
        post_mock.return_value = self._cinetpay_http_response(self._cinetpay_check_response("ACCEPTED", operator_id="op-paid-1"))

        response = self._post_cinetpay_webhook(paiement)
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.VALIDE)
        self.assertEqual(paiement.provider_transaction_id, "op-paid-1")
        self.assertTrue(AbonnementEntreprise.objects.filter(entreprise=self.entreprise, plan=self.plan_basic).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="CDF",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_cdf_accepted_webhook_activates_subscription_after_verification(self, post_mock):
        from django.utils import timezone

        ExchangeRate.objects.create(
            devise_source="USD",
            devise_cible="CDF",
            taux=Decimal("2300.00"),
            source_provider="test_cached_rate",
            date_taux=timezone.now(),
        )
        self.entreprise.devise = "CDF"
        self.entreprise.save(update_fields=["devise"])
        paiement = self._create_cinetpay_payment()
        post_mock.return_value = self._cinetpay_http_response(
            self._cinetpay_check_response("ACCEPTED", amount="23000", currency="CDF", operator_id="op-cdf-paid-1")
        )

        response = self._post_cinetpay_webhook(paiement)
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.VALIDE)
        self.assertEqual(paiement.provider_transaction_id, "op-cdf-paid-1")
        self.assertEqual(paiement.amount_paid, Decimal("23000.00"))
        self.assertEqual(paiement.paid_currency, "CDF")
        self.assertTrue(AbonnementEntreprise.objects.filter(entreprise=self.entreprise, plan=self.plan_basic).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_refused_webhook_marks_payment_failed(self, post_mock):
        paiement = self._create_cinetpay_payment()
        post_mock.return_value = self._cinetpay_http_response(self._cinetpay_check_response("REFUSED", operator_id="op-refused-1"))

        response = self._post_cinetpay_webhook(paiement)
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.ECHOUE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_waiting_webhook_keeps_payment_in_progress(self, post_mock):
        paiement = self._create_cinetpay_payment()
        post_mock.return_value = self._cinetpay_http_response(self._cinetpay_check_response("WAITING_FOR_CUSTOMER", operator_id="op-waiting-1"))

        response = self._post_cinetpay_webhook(paiement)
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_COURS)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_expired_webhook_marks_payment_expired(self, post_mock):
        paiement = self._create_cinetpay_payment()
        post_mock.return_value = self._cinetpay_http_response(self._cinetpay_check_response("EXPIRED", operator_id="op-expired-1"))

        response = self._post_cinetpay_webhook(paiement)
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EXPIRE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_cancelled_webhook_marks_payment_cancelled(self, post_mock):
        paiement = self._create_cinetpay_payment()
        post_mock.return_value = self._cinetpay_http_response(self._cinetpay_check_response("CANCELLED", operator_id="op-cancelled-1"))

        response = self._post_cinetpay_webhook(paiement)
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.ANNULE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_wrong_amount_is_rejected(self, post_mock):
        paiement = self._create_cinetpay_payment()
        post_mock.return_value = self._cinetpay_http_response(self._cinetpay_check_response("ACCEPTED", amount="9", operator_id="op-amount-1"))

        response = self._post_cinetpay_webhook(paiement)
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.ECHOUE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_wrong_currency_is_rejected(self, post_mock):
        paiement = self._create_cinetpay_payment()
        post_mock.return_value = self._cinetpay_http_response(self._cinetpay_check_response("ACCEPTED", currency="CDF", operator_id="op-currency-1"))

        response = self._post_cinetpay_webhook(paiement)
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.ECHOUE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_duplicate_webhook_is_idempotent(self, post_mock):
        paiement = self._create_cinetpay_payment()
        post_mock.return_value = self._cinetpay_http_response(self._cinetpay_check_response("ACCEPTED", operator_id="op-duplicate-1"))

        first_response = self._post_cinetpay_webhook(paiement)
        subscription = AbonnementEntreprise.objects.get(entreprise=self.entreprise)
        first_date_fin = subscription.date_fin
        second_response = self._post_cinetpay_webhook(paiement)
        subscription.refresh_from_db()

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(json.loads(second_response.content.decode("utf-8"))["duplicate"])
        self.assertEqual(subscription.date_fin, first_date_fin)
        self.assertTrue(ActivityLog.objects.filter(action="subscription_payment_webhook_duplicate", objet_id=paiement.id).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    @patch("core.services.payment_providers.requests.post")
    def test_cinetpay_provider_transaction_id_duplicate_is_rejected(self, post_mock):
        paiement = self._create_cinetpay_payment()
        post_mock.return_value = self._cinetpay_http_response(self._cinetpay_check_response("ACCEPTED", operator_id="op-shared-cinetpay"))
        self._post_cinetpay_webhook(paiement)
        other_entreprise = create_entreprise("Entreprise CinetPay Doublon")
        other_owner = create_user("owner-cinetpay-doublon", "proprietaire", other_entreprise)
        other_payment = self._create_cinetpay_payment(entreprise=other_entreprise, utilisateur=other_owner)

        response = self._post_cinetpay_webhook(other_payment)
        other_payment.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(other_payment.statut, PaiementAbonnement.Statut.ECHOUE)
        self.assertIn("Transaction provider", other_payment.failure_reason)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=other_entreprise).exists())

    def test_super_admin_validation_activates_subscription(self):
        paiement = create_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_pro,
            duree=PaiementAbonnement.Duree.MENSUEL,
            reference_paiement="BANK-001",
            utilisateur=self.owner,
        )

        subscription = validate_subscription_payment(paiement=paiement, super_admin=self.super_admin)
        paiement.refresh_from_db()
        self.entreprise.refresh_from_db()

        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.VALIDE)
        self.assertEqual(paiement.valide_par, self.super_admin)
        self.assertEqual(subscription.statut, AbonnementEntreprise.Statut.ACTIF)
        self.assertEqual(subscription.plan, self.plan_pro)
        self.assertEqual(self.entreprise.abonnement, self.plan_pro)
        self.assertEqual(self.entreprise.date_expiration, subscription.date_fin)
        self.assertEqual(paiement.montant_usd, Decimal("30"))

        self.client.force_login(self.owner)
        response = self.client.get(reverse("subscription_overview"))
        self.assertContains(response, "Mode d'activation")
        self.assertContains(response, "Paiement manuel validé par super admin")

    def test_super_admin_refusal_does_not_activate_subscription(self):
        paiement = create_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            reference_paiement="REFUSE-001",
            utilisateur=self.owner,
        )

        refuse_subscription_payment(paiement=paiement, super_admin=self.super_admin)
        paiement.refresh_from_db()

        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.REFUSE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    def test_super_admin_dashboard_can_validate_and_refuse_pending_payments(self):
        paiement_validate = create_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            reference_paiement="MOMO-VALID",
            utilisateur=self.owner,
        )
        other_entreprise = create_entreprise("Entreprise Paiement Refus")
        paiement_refuse = create_subscription_payment_request(
            entreprise=other_entreprise,
            plan=self.plan_pro,
            duree=PaiementAbonnement.Duree.ANNUEL,
            reference_paiement="MOMO-REFUSE",
            utilisateur=None,
        )

        self.client.force_login(self.super_admin)
        dashboard = self.client.get(reverse("super_admin_dashboard"))
        self.assertContains(dashboard, "Paiements en attente")
        self.assertContains(dashboard, "MOMO-VALID")
        self.assertContains(dashboard, "Valider le paiement")

        validate_response = self.client.post(
            reverse("super_admin_dashboard"),
            {"action": "validate_payment", "paiement_id": paiement_validate.id, "notes_validation": "Paiement confirme"},
        )
        self.assertRedirects(validate_response, reverse("super_admin_dashboard"))
        paiement_validate.refresh_from_db()
        self.assertEqual(paiement_validate.statut, PaiementAbonnement.Statut.VALIDE)
        self.assertEqual(paiement_validate.notes_validation, "Paiement confirme")

        refuse_response = self.client.post(
            reverse("super_admin_dashboard"),
            {"action": "refuse_payment", "paiement_id": paiement_refuse.id, "notes_validation": "Reference invalide"},
        )
        self.assertRedirects(refuse_response, reverse("super_admin_dashboard"))
        paiement_refuse.refresh_from_db()
        self.assertEqual(paiement_refuse.statut, PaiementAbonnement.Statut.REFUSE)
        self.assertEqual(paiement_refuse.notes_validation, "Reference invalide")

    @override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True, JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret")
    def test_automatic_subscription_payment_request_is_pending(self):
        paiement = create_automatic_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=self.owner,
        )

        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_ATTENTE)
        self.assertEqual(paiement.methode_paiement, PaiementAbonnement.Methode.AUTOMATIQUE)
        self.assertEqual(paiement.provider, "test")
        self.assertTrue(paiement.external_reference.startswith("SUB-"))
        self.assertEqual(paiement.amount_expected, Decimal("10.00"))
        self.assertIn(paiement.external_reference, paiement.checkout_url)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True, JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret")
    def test_automatic_payment_external_reference_is_unique(self):
        first = create_automatic_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=self.owner,
        )
        second = create_automatic_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_pro,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=self.owner,
        )

        self.assertNotEqual(first.external_reference, second.external_reference)

    @override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True, JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret")
    def test_payment_return_never_activates_subscription(self):
        paiement = create_automatic_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=self.owner,
        )

        self.client.force_login(self.owner)
        response = self.client.get(reverse("subscription_payment_return"), {"reference": paiement.external_reference})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "en cours de verification")
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    def test_cinetpay_payment_return_never_activates_subscription(self):
        paiement = self._create_cinetpay_payment()

        self.client.force_login(self.owner)
        response = self.client.get(reverse("subscription_payment_return"), {"reference": paiement.external_reference})
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_ATTENTE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(
        JOATHAM_AUTO_PAYMENT_ENABLED=True,
        JOATHAM_PAYMENT_PROVIDER="cinetpay",
        CINETPAY_SITE_ID="site-123",
        CINETPAY_APIKEY="api-key",
        CINETPAY_SECRET_KEY="secret-key",
        JOATHAM_PAYMENT_CALLBACK_URL="https://app.example.com/abonnement/webhooks/cinetpay/",
        JOATHAM_PAYMENT_RETURN_URL="https://app.example.com/abonnement/paiement/retour/",
        CINETPAY_CURRENCY="USD",
    )
    def test_cinetpay_payment_return_is_tenant_scoped(self):
        paiement = self._create_cinetpay_payment()
        other_entreprise = create_entreprise("Entreprise Retour CinetPay")
        other_owner = create_user("owner-retour-cinetpay", "proprietaire", other_entreprise)

        self.client.force_login(other_owner)
        response = self.client.get(reverse("subscription_payment_return"), {"reference": paiement.external_reference})
        paiement.refresh_from_db()
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucun paiement automatique récent n'a été trouvé pour votre entreprise")
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.EN_ATTENTE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=other_entreprise).exists())
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())
        self.assertNotIn(paiement.checkout_url, content)
        self.assertNotIn(paiement.provider_transaction_id or "provider-transaction-not-set", content)
        self.assertNotContains(response, "Statut :")
        self.assertNotContains(response, "Plan :")
        self.assertNotContains(response, paiement.plan.nom)
        self.assertNotContains(response, str(paiement.amount_expected))

    def test_payment_return_without_auto_payment_explains_manual_subscription(self):
        paiement = create_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            reference_paiement="BANK-MANUAL-RETURN",
            utilisateur=self.owner,
        )
        validate_subscription_payment(paiement=paiement, super_admin=self.super_admin)

        self.client.force_login(self.owner)
        response = self.client.get(reverse("subscription_payment_return"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cette page est réservée au retour d'un paiement automatique")
        self.assertContains(response, "Si votre abonnement a été validé manuellement par le super admin")
        self.assertContains(response, "Voir mon abonnement")
        self.assertContains(response, reverse("subscription_overview"))
        self.assertContains(response, "Voir les plans")
        self.assertContains(response, reverse("subscription_plan_list"))
        self.assertNotContains(response, "abonnement invalide")

    @override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True, JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret")
    def test_valid_webhook_activates_subscription(self):
        paiement = create_automatic_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=self.owner,
        )

        response = self._post_test_payment_webhook(
            paiement,
            event_id="evt-paid-1",
            amount="10.00",
            currency="USD",
            provider_transaction_id="tx-paid-1",
        )
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.VALIDE)
        self.assertEqual(paiement.provider_transaction_id, "tx-paid-1")
        self.assertEqual(paiement.amount_paid, Decimal("10.00"))
        self.assertTrue(AbonnementEntreprise.objects.filter(entreprise=self.entreprise, plan=self.plan_basic).exists())
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                action="subscription_auto_activated",
                objet_id=AbonnementEntreprise.objects.get(entreprise=self.entreprise).id,
            ).exists()
        )

        self.client.force_login(self.owner)
        overview = self.client.get(reverse("subscription_overview"))
        self.assertContains(overview, "Paiement automatique confirmé")

    @override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True, JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret")
    def test_webhook_wrong_amount_is_rejected(self):
        paiement = create_automatic_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=self.owner,
        )

        response = self._post_test_payment_webhook(
            paiement,
            event_id="evt-amount-1",
            amount="9.00",
            currency="USD",
            provider_transaction_id="tx-amount-1",
        )
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.ECHOUE)
        self.assertIn("Montant", paiement.failure_reason)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True, JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret")
    def test_webhook_wrong_currency_is_rejected(self):
        paiement = create_automatic_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=self.owner,
        )

        response = self._post_test_payment_webhook(
            paiement,
            event_id="evt-currency-1",
            amount="10.00",
            currency="CDF",
            provider_transaction_id="tx-currency-1",
        )
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.ECHOUE)
        self.assertIn("Devise", paiement.failure_reason)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True, JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret")
    def test_webhook_unknown_transaction_is_rejected(self):
        response = self.client.post(
            reverse("subscription_payment_webhook", kwargs={"provider": "test"}),
            data=json.dumps(
                {
                    "external_reference": "SUB-UNKNOWN",
                    "event_id": "evt-unknown-1",
                    "status": "paid",
                    "amount": "10.00",
                    "currency": "USD",
                    "provider_transaction_id": "tx-unknown-1",
                }
            ),
            content_type="application/json",
            HTTP_X_JOATHAM_TEST_SIGNATURE="test-secret",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True, JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret")
    def test_duplicate_webhook_is_idempotent(self):
        paiement = create_automatic_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=self.owner,
        )

        first_response = self._post_test_payment_webhook(
            paiement,
            event_id="evt-duplicate-1",
            amount="10.00",
            currency="USD",
            provider_transaction_id="tx-duplicate-1",
        )
        first_subscription = AbonnementEntreprise.objects.get(entreprise=self.entreprise)
        first_date_fin = first_subscription.date_fin
        second_response = self._post_test_payment_webhook(
            paiement,
            event_id="evt-duplicate-1",
            amount="10.00",
            currency="USD",
            provider_transaction_id="tx-duplicate-1",
        )
        first_subscription.refresh_from_db()

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_subscription.date_fin, first_date_fin)
        self.assertTrue(ActivityLog.objects.filter(action="subscription_payment_webhook_duplicate").exists())

    @override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True, JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret")
    def test_failed_webhook_does_not_activate_subscription(self):
        paiement = create_automatic_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=self.owner,
        )

        response = self._post_test_payment_webhook(
            paiement,
            event_id="evt-failed-1",
            status="failed",
            amount="10.00",
            currency="USD",
            provider_transaction_id="tx-failed-1",
        )
        paiement.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(paiement.statut, PaiementAbonnement.Statut.ECHOUE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())

    @override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True, JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret")
    def test_provider_transaction_id_duplicate_does_not_double_activate(self):
        paiement = create_automatic_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=self.owner,
        )
        self._post_test_payment_webhook(
            paiement,
            event_id="evt-tx-1",
            amount="10.00",
            currency="USD",
            provider_transaction_id="tx-shared",
        )
        other_entreprise = create_entreprise("Entreprise Transaction Doublon")
        other_owner = create_user("owner-transaction-doublon", "proprietaire", other_entreprise)
        other_payment = create_automatic_subscription_payment_request(
            entreprise=other_entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=other_owner,
        )

        response = self._post_test_payment_webhook(
            other_payment,
            event_id="evt-tx-2",
            amount="10.00",
            currency="USD",
            provider_transaction_id="tx-shared",
        )
        other_payment.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(other_payment.statut, PaiementAbonnement.Statut.ECHOUE)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=other_entreprise).exists())

    @override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True, JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET="test-secret")
    def test_super_admin_dashboard_shows_automatic_pending_payment(self):
        paiement = create_automatic_subscription_payment_request(
            entreprise=self.entreprise,
            plan=self.plan_basic,
            duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test",
            utilisateur=self.owner,
        )

        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("super_admin_dashboard"))

        self.assertContains(response, "Paiements en attente")
        self.assertContains(response, paiement.external_reference)

    def _create_cinetpay_payment(self, *, entreprise=None, utilisateur=None, plan=None):
        with patch("core.services.payment_providers.requests.post") as post_mock:
            post_mock.return_value = self._cinetpay_http_response(
                {
                    "code": "201",
                    "message": "CREATED",
                    "data": {
                        "payment_token": "payment-token-test",
                        "payment_url": "https://checkout.cinetpay.com/payment/payment-token-test",
                    },
                    "api_response_id": "api-init-test",
                }
            )
            return create_automatic_subscription_payment_request(
                entreprise=entreprise or self.entreprise,
                plan=plan or self.plan_basic,
                duree=PaiementAbonnement.Duree.MENSUEL,
                provider="cinetpay",
                utilisateur=utilisateur or self.owner,
            )

    def _cinetpay_notification_payload(self, paiement):
        return {
            "cpm_site_id": "site-123",
            "cpm_trans_id": paiement.external_reference,
            "cpm_trans_date": "2026-05-29 10:00:00",
            "cpm_amount": "10",
            "cpm_currency": "USD",
            "signature": "signature",
            "payment_method": "MOBILE_MONEY",
            "cel_phone_num": "+243970258117",
            "cpm_phone_prefixe": "243",
            "cpm_language": "fr",
            "cpm_version": "V4",
            "cpm_payment_config": "Single",
            "cpm_page_action": "Payment",
            "cpm_custom": paiement.external_reference,
            "cpm_designation": "Abonnement JOATHAM Manager",
            "cpm_error_message": "",
        }

    def _post_cinetpay_webhook(self, paiement):
        payload = self._cinetpay_notification_payload(paiement)
        token_source = "".join(str(payload.get(field, "")) for field in CINETPAY_NOTIFICATION_HMAC_FIELDS)
        token = hmac.new(b"secret-key", token_source.encode("utf-8"), hashlib.sha256).hexdigest()
        return self.client.post(
            reverse("subscription_payment_webhook", kwargs={"provider": "cinetpay"}),
            data=payload,
            HTTP_X_TOKEN=token,
        )

    def _cinetpay_check_response(self, status, *, amount="10", currency="USD", operator_id="op-test"):
        return {
            "code": "00" if status == "ACCEPTED" else "627",
            "message": "SUCCES" if status == "ACCEPTED" else status,
            "data": {
                "amount": amount,
                "currency": currency,
                "status": status,
                "payment_method": "MOBILE_MONEY",
                "description": "Abonnement JOATHAM Manager",
                "metadata": None,
                "operator_id": operator_id,
                "payment_date": "2026-05-29 10:00:00",
            },
            "api_response_id": f"api-{status.lower()}-{operator_id}",
        }

    def _cinetpay_http_response(self, payload, status_code=200):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = payload
        return response

    def _post_test_payment_webhook(
        self,
        paiement,
        *,
        event_id,
        amount,
        currency,
        provider_transaction_id,
        status="paid",
    ):
        return self.client.post(
            reverse("subscription_payment_webhook", kwargs={"provider": "test"}),
            data=json.dumps(
                {
                    "external_reference": paiement.external_reference,
                    "event_id": event_id,
                    "status": status,
                    "amount": amount,
                    "currency": currency,
                    "provider_transaction_id": provider_transaction_id,
                }
            ),
            content_type="application/json",
            HTTP_X_JOATHAM_TEST_SIGNATURE="test-secret",
        )
