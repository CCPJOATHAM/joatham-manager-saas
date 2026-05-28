from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import PaiementAbonnement
from core.services.product_policy import (
    ACCESS_INCLUDED_PLAN,
    MODULE_ACCESS_POLICY,
    PREMIUM_BUSINESS_MODULE_DENYLIST,
    can_access_module,
    get_module_access_level,
    get_module_access_state,
)
from core.services.quotas import (
    FREE_PLAN_CLIENT_LIMIT,
    FREE_PLAN_EXPENSE_MONTHLY_LIMIT,
    FREE_PLAN_INVOICE_LIMIT,
    FREE_PLAN_PRODUCT_LIMIT,
    PlanQuotaExceeded,
    assert_client_quota_available,
    assert_expense_quota_available,
    assert_invoice_quota_available,
    assert_product_quota_available,
)
from core.services.subscription import (
    OFFICIAL_COMMERCIAL_PLAN_CODES,
    activate_free_plan_for_entreprise,
    activate_subscription_for_entreprise,
    create_subscription_payment_request,
    get_commercial_plans_queryset,
    get_default_paid_plans,
    get_or_create_free_plan,
    get_subscription_price_usd,
)
from joatham_billing.models import Facture
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_clients.models import Client
from joatham_depenses.models import Depense
from joatham_products.models import Produit
from joatham_users.models import Abonnement


def create_default_plan(code):
    payload = next(plan for plan in get_default_paid_plans() if plan["code"] == code)
    return Abonnement.objects.create(**payload, actif=True)


class SubscriptionPlanMatrixTests(TestCase):
    def setUp(self):
        self.free_company = create_entreprise("Plan Free")
        self.starter_company = create_entreprise("Plan Starter")
        self.pro_company = create_entreprise("Plan Pro")
        self.premium_company = create_entreprise("Plan Premium")
        self.free_owner = create_user("owner-plan-free", "proprietaire", self.free_company)
        self.starter_owner = create_user("owner-plan-starter", "proprietaire", self.starter_company)
        self.pro_owner = create_user("owner-plan-pro", "proprietaire", self.pro_company)
        self.premium_owner = create_user("owner-plan-premium", "proprietaire", self.premium_company)

        activate_free_plan_for_entreprise(entreprise=self.free_company, utilisateur=self.free_owner)
        activate_subscription_for_entreprise(
            entreprise=self.starter_company,
            plan=create_default_plan("starter"),
            utilisateur=self.starter_owner,
        )
        activate_subscription_for_entreprise(
            entreprise=self.pro_company,
            plan=create_default_plan("pro"),
            utilisateur=self.pro_owner,
        )
        activate_subscription_for_entreprise(
            entreprise=self.premium_company,
            plan=create_default_plan("premium"),
            utilisateur=self.premium_owner,
        )

    def test_official_plan_prices_match_current_pricing_grid(self):
        free_plan = get_or_create_free_plan()
        paid_plans = {plan["code"]: plan for plan in get_default_paid_plans()}

        self.assertEqual(Decimal(str(free_plan.prix)), Decimal("0"))
        self.assertEqual(free_plan.devise, "USD")
        self.assertEqual(Decimal(str(paid_plans["starter"]["prix"])), Decimal("10"))
        self.assertEqual(paid_plans["starter"]["prix_annuel"], Decimal("120.00"))
        self.assertEqual(Decimal(str(paid_plans["pro"]["prix"])), Decimal("15"))
        self.assertEqual(paid_plans["pro"]["prix_annuel"], Decimal("180.00"))
        self.assertEqual(paid_plans["premium"]["nom"], "Premium Business")
        self.assertEqual(Decimal(str(paid_plans["premium"]["prix"])), Decimal("20"))
        self.assertEqual(paid_plans["premium"]["prix_annuel"], Decimal("240.00"))

    def test_official_plan_module_matrix_matches_commercial_strategy(self):
        free_plan = get_or_create_free_plan()
        paid_plans = {plan["code"]: plan for plan in get_default_paid_plans()}

        self.assertEqual(
            set(free_plan.modules_inclus),
            {"dashboard", "clients", "services", "billing", "factures", "subscription", "abonnements"},
        )
        self.assertTrue({"expenses", "depenses", "products", "produits"}.issubset(set(paid_plans["starter"]["modules_inclus"])))
        self.assertFalse({"caisse", "rh", "advanced_reports"} & set(paid_plans["starter"]["modules_inclus"]))
        self.assertFalse(paid_plans["starter"]["acces_comptabilite"])
        self.assertTrue(
            {
                "caisse",
                "caisse_reports",
                "caisse_exports",
                "caisse_validation",
                "stock",
                "stock_reports",
                "stock_exports",
                "inventory",
                "payments",
                "payment_validation",
                "payments_reports",
                "payments_exports",
                "accounting",
                "accounting_reports",
                "accounting_exports",
                "apprenants",
                "users",
                "audit",
            }.issubset(set(paid_plans["pro"]["modules_inclus"]))
        )
        self.assertFalse({"rh", "advanced_reports"} & set(paid_plans["pro"]["modules_inclus"]))
        self.assertTrue(paid_plans["pro"]["acces_comptabilite"])

    def test_official_plan_payment_requests_use_current_monthly_prices(self):
        starter = self.starter_company.abonnement_entreprise.plan
        pro = self.pro_company.abonnement_entreprise.plan
        premium = self.premium_company.abonnement_entreprise.plan

        self.assertEqual(get_subscription_price_usd(plan=starter, duree=PaiementAbonnement.Duree.MENSUEL), Decimal("10"))
        self.assertEqual(get_subscription_price_usd(plan=pro, duree=PaiementAbonnement.Duree.MENSUEL), Decimal("15"))
        self.assertEqual(get_subscription_price_usd(plan=premium, duree=PaiementAbonnement.Duree.MENSUEL), Decimal("20"))

        payment = create_subscription_payment_request(
            entreprise=self.starter_company,
            plan=starter,
            duree=PaiementAbonnement.Duree.MENSUEL,
            reference_paiement="PRICE-STARTER-10",
            utilisateur=self.starter_owner,
        )

        self.assertEqual(payment.montant_usd, Decimal("10.00"))

    def test_free_plan_blocks_advanced_modules(self):
        self.assertTrue(can_access_module(self.free_owner, "dashboard"))
        self.assertTrue(can_access_module(self.free_owner, "billing"))
        self.assertFalse(can_access_module(self.free_owner, "expenses"))
        self.assertFalse(can_access_module(self.free_owner, "products"))
        self.assertFalse(can_access_module(self.free_owner, "caisse"))
        self.assertFalse(can_access_module(self.free_owner, "stock"))
        self.assertFalse(can_access_module(self.free_owner, "stock_reports"))
        self.assertFalse(can_access_module(self.free_owner, "inventory"))
        self.assertFalse(can_access_module(self.free_owner, "stock_exports"))
        self.assertFalse(can_access_module(self.free_owner, "caisse_reports"))
        self.assertFalse(can_access_module(self.free_owner, "payments"))
        self.assertFalse(can_access_module(self.free_owner, "accounting"))
        self.assertFalse(can_access_module(self.free_owner, "rh"))
        self.assertFalse(can_access_module(self.free_owner, "advanced_reports"))

    def test_starter_allows_simple_operations_but_blocks_advanced_modules(self):
        self.assertTrue(can_access_module(self.starter_owner, "expenses"))
        self.assertTrue(can_access_module(self.starter_owner, "products"))
        self.assertFalse(can_access_module(self.starter_owner, "caisse"))
        self.assertFalse(can_access_module(self.starter_owner, "inventory"))
        self.assertFalse(can_access_module(self.starter_owner, "payments"))
        self.assertFalse(can_access_module(self.starter_owner, "accounting"))
        self.assertFalse(can_access_module(self.starter_owner, "rh"))
        self.assertFalse(can_access_module(self.starter_owner, "advanced_reports"))
        state = get_module_access_state(self.starter_company, "inventory")
        self.assertEqual(state["reason"], "module_not_in_plan")

    def test_pro_allows_operational_modules_but_blocks_rh_and_advanced_reports(self):
        self.assertTrue(can_access_module(self.pro_owner, "caisse"))
        self.assertTrue(can_access_module(self.pro_owner, "stock"))
        self.assertTrue(can_access_module(self.pro_owner, "stock_reports"))
        self.assertTrue(can_access_module(self.pro_owner, "stock_exports"))
        self.assertTrue(can_access_module(self.pro_owner, "inventory"))
        self.assertTrue(can_access_module(self.pro_owner, "caisse_reports"))
        self.assertTrue(can_access_module(self.pro_owner, "caisse_exports"))
        self.assertTrue(can_access_module(self.pro_owner, "caisse_integrations"))
        self.assertTrue(can_access_module(self.pro_owner, "caisse_validation"))
        self.assertTrue(can_access_module(self.pro_owner, "payments"))
        self.assertTrue(can_access_module(self.pro_owner, "payment_validation"))
        self.assertTrue(can_access_module(self.pro_owner, "payments_reports"))
        self.assertTrue(can_access_module(self.pro_owner, "payments_exports"))
        self.assertTrue(can_access_module(self.pro_owner, "accounting"))
        self.assertTrue(can_access_module(self.pro_owner, "accounting_reports"))
        self.assertTrue(can_access_module(self.pro_owner, "accounting_exports"))
        self.assertTrue(can_access_module(self.pro_owner, "apprenants"))
        self.assertTrue(can_access_module(self.pro_owner, "users"))
        self.assertTrue(can_access_module(self.pro_owner, "audit"))
        self.assertFalse(can_access_module(self.pro_owner, "mobile_money"))
        self.assertFalse(can_access_module(self.pro_owner, "rh"))
        self.assertFalse(can_access_module(self.pro_owner, "advanced_reports"))
        self.assertFalse(can_access_module(self.pro_owner, "advanced_reports_exports"))
        self.assertFalse(can_access_module(self.pro_owner, "audit_advanced"))
        self.assertFalse(can_access_module(self.pro_owner, "messages"))

    def test_premium_allows_every_current_advanced_module(self):
        for module_name in MODULE_ACCESS_POLICY:
            with self.subTest(module_name=module_name):
                if module_name in PREMIUM_BUSINESS_MODULE_DENYLIST:
                    self.assertFalse(can_access_module(self.premium_owner, module_name))
                else:
                    self.assertTrue(can_access_module(self.premium_owner, module_name))

    def test_premium_business_allows_future_declared_modules_by_default(self):
        patched_policy = {**MODULE_ACCESS_POLICY, "future_module": ACCESS_INCLUDED_PLAN}

        with patch("core.services.product_policy.MODULE_ACCESS_POLICY", patched_policy):
            self.assertTrue(can_access_module(self.premium_owner, "future_module"))
            self.assertFalse(can_access_module(self.pro_owner, "future_module"))

    def test_premium_module_aliases_share_the_same_access_decision(self):
        for english_name, french_name in (
            ("billing", "factures"),
            ("accounting", "comptabilite"),
            ("payments", "paiements"),
            ("products", "produits"),
            ("inventory", "inventaire"),
            ("users", "utilisateurs"),
            ("subscription", "abonnements"),
            ("expenses", "depenses"),
        ):
            with self.subTest(module=english_name):
                self.assertEqual(get_module_access_level(english_name), get_module_access_level(french_name))
                self.assertTrue(can_access_module(self.premium_owner, english_name))
                self.assertTrue(can_access_module(self.premium_owner, french_name))

    def test_starter_plan_does_not_gain_premium_alias_access(self):
        for module_name in ("accounting", "comptabilite", "payments", "paiements", "caisse", "inventory", "inventaire"):
            with self.subTest(module=module_name):
                self.assertFalse(can_access_module(self.starter_owner, module_name))

    def test_starter_plan_keeps_access_to_included_aliases(self):
        for english_name, french_name in (
            ("billing", "factures"),
            ("products", "produits"),
            ("subscription", "abonnements"),
            ("expenses", "depenses"),
        ):
            with self.subTest(module=english_name):
                self.assertTrue(can_access_module(self.starter_owner, english_name))
                self.assertTrue(can_access_module(self.starter_owner, french_name))


class SubscriptionQuotaMatrixTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Quotas Free")
        self.owner = create_user("owner-quota-free", "proprietaire", self.entreprise)
        free_plan = get_or_create_free_plan()
        activate_free_plan_for_entreprise(entreprise=self.entreprise, plan=free_plan, utilisateur=self.owner)

    def test_free_plan_invoice_product_client_and_expense_quotas_are_enforced(self):
        for index in range(FREE_PLAN_INVOICE_LIMIT):
            Facture.objects.create(
                entreprise=self.entreprise,
                client_nom=f"Client {index}",
                montant=Decimal("10.00"),
                tva=Decimal("0.00"),
            )
        with self.assertRaises(PlanQuotaExceeded):
            assert_invoice_quota_available(self.entreprise, as_of=timezone.localdate())

        for index in range(FREE_PLAN_PRODUCT_LIMIT):
            Produit.objects.create(
                entreprise=self.entreprise,
                nom=f"Produit {index}",
                reference=f"P-{index}",
                prix_unitaire=Decimal("1.00"),
            )
        with self.assertRaises(PlanQuotaExceeded):
            assert_product_quota_available(self.entreprise)

        for index in range(FREE_PLAN_CLIENT_LIMIT):
            Client.objects.create(
                entreprise=self.entreprise,
                nom=f"Client quota {index}",
                telephone="",
                email=f"quota-{index}@example.com",
            )
        with self.assertRaises(PlanQuotaExceeded):
            assert_client_quota_available(self.entreprise)

        for index in range(FREE_PLAN_EXPENSE_MONTHLY_LIMIT):
            Depense.objects.create(
                entreprise=self.entreprise,
                description=f"Depense {index}",
                montant=Decimal("1.00"),
            )
        with self.assertRaises(PlanQuotaExceeded):
            assert_expense_quota_available(self.entreprise, as_of=timezone.localdate())


class SaasPlanSeedTests(TestCase):
    def test_subscription_plan_list_displays_current_official_prices(self):
        entreprise = create_entreprise("Entreprise Plans Prix")
        entreprise.devise = "USD"
        entreprise.save(update_fields=["devise"])
        owner = create_user("owner-plans-prices", "proprietaire", entreprise)
        call_command("seed_saas_plans", stdout=StringIO())
        activate_free_plan_for_entreprise(entreprise=entreprise, utilisateur=owner)

        self.client.force_login(owner)
        response = self.client.get(reverse("subscription_plan_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gratuit")
        self.assertContains(response, "0 USD")
        self.assertContains(response, "Starter")
        self.assertContains(response, "10,00 USD")
        self.assertContains(response, "Pro")
        self.assertContains(response, "15,00 USD")
        self.assertContains(response, "Premium Business")
        self.assertContains(response, "20,00 USD")

    def test_subscription_plan_list_uses_commercial_labels_and_coherent_limits(self):
        entreprise = create_entreprise("Entreprise Plans UX")
        entreprise.devise = "USD"
        entreprise.save(update_fields=["devise"])
        owner = create_user("owner-plans-ux", "proprietaire", entreprise)
        call_command("seed_saas_plans", stdout=StringIO())
        activate_free_plan_for_entreprise(entreprise=entreprise, utilisateur=owner)

        self.client.force_login(owner)
        response = self.client.get(reverse("subscription_plan_list"))

        self.assertEqual(response.status_code, 200)
        cards = {card["plan"].code: card for card in response.context["plan_cards"]}
        free_card = cards["free"]
        starter_card = cards["starter"]
        pro_card = cards["pro"]
        premium_card = cards["premium"]

        self.assertContains(response, "Plan découverte pour tester JOATHAM Manager")
        self.assertContains(response, "Gestion simple pour une petite activité")
        self.assertContains(response, "Gestion avancée avec caisse")
        self.assertContains(response, "Accès complet à JOATHAM Manager")
        self.assertNotContains(response, "caisse simple")
        for card in cards.values():
            self.assertFalse(any("non inclus" in feature.lower() for feature in card["features"]))

        self.assertNotIn("Produits", free_card["included_modules"])
        self.assertNotIn("Dépenses", free_card["included_modules"])
        self.assertNotIn("Caisse", free_card["included_modules"])
        self.assertIn("Produits", free_card["non_included"])
        self.assertIn("Dépenses", free_card["non_included"])
        self.assertIn("Caisse", free_card["non_included"])
        self.assertIn("Ressources humaines", free_card["non_included"])
        self.assertNotIn("Produits", [row["label"] for row in free_card["limits"]])
        self.assertNotIn("Dépenses / mois", [row["label"] for row in free_card["limits"]])
        self.assertNotIn("Caisses actives", [row["label"] for row in free_card["limits"]])

        self.assertIn("Produits", starter_card["included_modules"])
        self.assertIn("Dépenses", starter_card["included_modules"])
        self.assertNotIn("Caisse", starter_card["included_modules"])
        self.assertIn("Caisse avancée", starter_card["non_included"])
        self.assertIn("Ressources humaines", starter_card["non_included"])
        self.assertIn("Rapports avancés", starter_card["non_included"])

        pro_limit_values = {row["label"]: row["value"] for row in pro_card["limits"]}
        self.assertIn("Comptabilité", pro_card["included_modules"])
        self.assertEqual(pro_limit_values["Comptabilité"], "Incluse")
        self.assertIn("Ressources humaines complètes", pro_card["non_included"])
        self.assertIn("Rapports avancés", pro_card["non_included"])

        self.assertIn("Ressources humaines", premium_card["included_modules"])
        self.assertIn("Rapports avancés", premium_card["included_modules"])
        self.assertEqual(premium_card["non_included"], [])
        self.assertEqual(premium_card["included_modules"].count("Facturation"), 1)
        self.assertEqual(premium_card["included_modules"].count("Dépenses"), 1)
        self.assertEqual(premium_card["included_modules"].count("Produits"), 1)
        self.assertNotContains(response, "advanced_reports")
        self.assertNotContains(response, "payments_exports")
        self.assertNotContains(response, "accounting_exports")

    def test_seed_updates_official_plan_prices(self):
        Abonnement.objects.create(
            nom="Starter",
            code="starter",
            prix=19,
            prix_annuel=Decimal("190.00"),
            duree_jours=30,
            actif=True,
        )
        Abonnement.objects.create(
            nom="Pro",
            code="pro",
            prix=49,
            prix_annuel=Decimal("490.00"),
            duree_jours=30,
            actif=True,
        )
        Abonnement.objects.create(
            nom="Premium / Business",
            code="premium",
            prix=99,
            prix_annuel=Decimal("990.00"),
            duree_jours=30,
            actif=True,
        )

        call_command("seed_saas_plans", stdout=StringIO())

        free = Abonnement.objects.get(code="free")
        starter = Abonnement.objects.get(code="starter")
        pro = Abonnement.objects.get(code="pro")
        premium = Abonnement.objects.get(code="premium")

        self.assertEqual(Decimal(str(free.prix)), Decimal("0"))
        self.assertEqual(free.devise, "USD")
        self.assertEqual(Decimal(str(starter.prix)), Decimal("10"))
        self.assertEqual(starter.prix_annuel, Decimal("120.00"))
        self.assertEqual(Decimal(str(pro.prix)), Decimal("15"))
        self.assertEqual(pro.prix_annuel, Decimal("180.00"))
        self.assertTrue(pro.acces_comptabilite)
        self.assertEqual(premium.nom, "Premium Business")
        self.assertEqual(Decimal(str(premium.prix)), Decimal("20"))
        self.assertEqual(premium.prix_annuel, Decimal("240.00"))
        self.assertNotIn("caisse", free.modules_inclus)
        self.assertNotIn("products", free.modules_inclus)
        self.assertIn("products", starter.modules_inclus)
        self.assertNotIn("caisse", starter.modules_inclus)
        self.assertIn("caisse", pro.modules_inclus)
        self.assertIn("payments", pro.modules_inclus)
        self.assertIn("accounting", pro.modules_inclus)
        self.assertNotIn("rh", pro.modules_inclus)
        self.assertIn("rh", premium.modules_inclus)
        self.assertIn("advanced_reports", premium.modules_inclus)

    def test_seed_keeps_only_official_commercial_plans_active(self):
        legacy_trial = Abonnement.objects.create(
            nom="Plan d'essai",
            code="trial-default",
            prix=0,
            duree_jours=14,
            actif=True,
            description="Ancienne offre commerciale",
        )

        call_command("seed_saas_plans", stdout=StringIO())

        legacy_trial.refresh_from_db()
        self.assertFalse(legacy_trial.actif)
        self.assertIn("legacy", legacy_trial.description)

        official_codes = set(OFFICIAL_COMMERCIAL_PLAN_CODES)
        commercial_codes = set(get_commercial_plans_queryset().values_list("code", flat=True))
        self.assertEqual(commercial_codes, official_codes)
        self.assertFalse(get_commercial_plans_queryset().filter(code="trial-default").exists())
