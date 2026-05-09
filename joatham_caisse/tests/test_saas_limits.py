from django.test import TestCase

from core.services.quotas import FREE_PLAN_CASHBOX_LIMIT, PlanQuotaExceeded
from core.services.subscription import get_or_create_default_free_plan, start_free_plan_for_entreprise
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_caisse.models import Caisse
from joatham_caisse.services.caisse import create_caisse_for_entreprise


class CashboxSaasLimitTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Freemium Caisse")
        self.owner = create_user("owner-cashbox-free", "proprietaire", self.entreprise)
        free_plan = get_or_create_default_free_plan()
        start_free_plan_for_entreprise(entreprise=self.entreprise, plan=free_plan, utilisateur=self.owner)

    def test_free_plan_is_limited_to_one_active_cashbox(self):
        first = create_caisse_for_entreprise(
            entreprise=self.entreprise,
            nom="Caisse A",
            code="CAISSE-A",
            utilisateur=self.owner,
        )
        self.assertEqual(first.entreprise, self.entreprise)
        self.assertEqual(Caisse.objects.filter(entreprise=self.entreprise, est_active=True).count(), FREE_PLAN_CASHBOX_LIMIT)

        with self.assertRaises(PlanQuotaExceeded):
            create_caisse_for_entreprise(
                entreprise=self.entreprise,
                nom="Caisse B",
                code="CAISSE-B",
                utilisateur=self.owner,
            )

