from django.test import TestCase
from django.urls import reverse

from core.services.subscription import activate_subscription_for_entreprise, get_default_paid_plans
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement


def create_default_plan(code):
    payload = next(plan for plan in get_default_paid_plans() if plan["code"] == code)
    return Abonnement.objects.create(**payload, actif=True)


class ProductSubscriptionAccessTests(TestCase):
    def test_starter_cannot_access_physical_inventory(self):
        entreprise = create_entreprise("Starter Inventory")
        owner = create_user("owner-starter-inventory", "proprietaire", entreprise)
        activate_subscription_for_entreprise(
            entreprise=entreprise,
            plan=create_default_plan("starter"),
            utilisateur=owner,
        )
        self.client.force_login(owner)

        stock_response = self.client.get(reverse("stock_movement_list"))
        inventory_response = self.client.get(reverse("inventory_list"))

        self.assertEqual(stock_response.status_code, 200)
        self.assertRedirects(inventory_response, reverse("abonnement_expire") + "?module=inventory&reason=module_not_in_plan")

    def test_pro_can_access_stock_reports(self):
        entreprise = create_entreprise("Pro Stock")
        owner = create_user("owner-pro-stock", "proprietaire", entreprise)
        activate_subscription_for_entreprise(
            entreprise=entreprise,
            plan=create_default_plan("pro"),
            utilisateur=owner,
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("stock_reports"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("report", response.context)
