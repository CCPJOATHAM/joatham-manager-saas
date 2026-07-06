from django.test import TestCase
from django.urls import reverse

from core.services.subscription import activate_subscription_for_entreprise, get_default_paid_plans
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement


def create_default_plan(code):
    payload = next(plan for plan in get_default_paid_plans() if plan["code"] == code)
    return Abonnement.objects.create(**payload, actif=True)


class CashboxSubscriptionAccessTests(TestCase):
    def test_starter_cannot_open_cashbox_module_or_cash_reports(self):
        entreprise = create_entreprise("Starter Caisse")
        owner = create_user("owner-starter-caisse", "proprietaire", entreprise)
        activate_subscription_for_entreprise(
            entreprise=entreprise,
            plan=create_default_plan("starter"),
            utilisateur=owner,
        )
        self.client.force_login(owner)

        cashbox_response = self.client.get(reverse("caisse_list"))
        reports_response = self.client.get(reverse("caisse_reports"))

        self.assertRedirects(
            cashbox_response,
            reverse("abonnement_expire") + "?module=caisse&reason=module_not_in_plan",
        )
        self.assertRedirects(
            reports_response,
            reverse("abonnement_expire") + "?module=caisse_reports&reason=module_not_in_plan",
        )

    def test_pro_can_access_complete_cashbox_reports(self):
        entreprise = create_entreprise("Pro Caisse")
        owner = create_user("owner-pro-caisse", "proprietaire", entreprise)
        activate_subscription_for_entreprise(
            entreprise=entreprise,
            plan=create_default_plan("pro"),
            utilisateur=owner,
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("caisse_reports"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("report", response.context)
