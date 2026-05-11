from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.services.product_policy import can_access_module, get_module_access_state
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
    activate_subscription_for_entreprise,
    get_default_paid_plans,
    get_or_create_default_free_plan,
    start_free_plan_for_entreprise,
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

        start_free_plan_for_entreprise(entreprise=self.free_company, utilisateur=self.free_owner)
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

    def test_free_plan_blocks_advanced_modules(self):
        self.assertTrue(can_access_module(self.free_owner, "dashboard"))
        self.assertTrue(can_access_module(self.free_owner, "billing"))
        self.assertFalse(can_access_module(self.free_owner, "stock"))
        self.assertFalse(can_access_module(self.free_owner, "inventory"))
        self.assertFalse(can_access_module(self.free_owner, "stock_exports"))
        self.assertFalse(can_access_module(self.free_owner, "caisse_reports"))
        self.assertFalse(can_access_module(self.free_owner, "accounting"))

    def test_starter_allows_simple_cashbox_but_blocks_physical_inventory(self):
        self.assertTrue(can_access_module(self.starter_owner, "caisse"))
        self.assertFalse(can_access_module(self.starter_owner, "inventory"))
        state = get_module_access_state(self.starter_company, "inventory")
        self.assertEqual(state["reason"], "module_not_in_plan")

    def test_pro_allows_stock_inventory_cashbox_exports_and_users(self):
        self.assertTrue(can_access_module(self.pro_owner, "stock"))
        self.assertTrue(can_access_module(self.pro_owner, "stock_reports"))
        self.assertTrue(can_access_module(self.pro_owner, "stock_exports"))
        self.assertTrue(can_access_module(self.pro_owner, "inventory"))
        self.assertTrue(can_access_module(self.pro_owner, "caisse_integrations"))
        self.assertTrue(can_access_module(self.pro_owner, "users"))
        self.assertFalse(can_access_module(self.pro_owner, "accounting"))

    def test_premium_allows_every_current_advanced_module(self):
        for module_name in ("stock", "inventory", "caisse_integrations", "accounting", "audit", "messages"):
            with self.subTest(module_name=module_name):
                self.assertTrue(can_access_module(self.premium_owner, module_name))


class SubscriptionQuotaMatrixTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Quotas Free")
        self.owner = create_user("owner-quota-free", "proprietaire", self.entreprise)
        free_plan = get_or_create_default_free_plan()
        start_free_plan_for_entreprise(entreprise=self.entreprise, plan=free_plan, utilisateur=self.owner)

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
