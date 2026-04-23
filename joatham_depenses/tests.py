from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.services.subscription import start_trial_for_entreprise
from joatham_billing.tests.factories import create_entreprise, create_user
from core.services.currency import format_amount_for_entreprise, format_decimal_number
from joatham_depenses.models import Depense
from joatham_depenses.selectors.depenses import get_depenses_by_entreprise
from joatham_depenses.services.depenses_service import get_depenses_kpis, get_depenses_total, list_depenses_for_entreprise
from joatham_users.models import Abonnement


class DepensesServiceTests(TestCase):
    def setUp(self):
        self.entreprise_a = create_entreprise("Entreprise Depenses A")
        self.entreprise_b = create_entreprise("Entreprise Depenses B")
        self.gestionnaire_a = create_user("gestion-dep-a", "gestionnaire", self.entreprise_a)
        self.comptable_a = create_user("compta-dep-a", "comptable", self.entreprise_a)
        self.plan = Abonnement.objects.create(nom="Depenses", code="depenses", prix=19, duree_jours=30, actif=True)
        start_trial_for_entreprise(entreprise=self.entreprise_a, plan=self.plan, utilisateur=self.gestionnaire_a)
        self.depense_a = Depense.objects.create(
            description="Papeterie",
            montant=Decimal("40.00"),
            entreprise=self.entreprise_a,
        )
        self.depense_b = Depense.objects.create(
            description="Transport",
            montant=Decimal("15.00"),
            entreprise=self.entreprise_b,
        )

    def test_depense_selector_scopes_to_entreprise(self):
        self.assertEqual(list(get_depenses_by_entreprise(self.entreprise_a)), [self.depense_a])

    def test_depense_service_scopes_and_computes_total(self):
        queryset = list_depenses_for_entreprise(self.entreprise_a)
        self.assertEqual(list(queryset), [self.depense_a])
        self.assertEqual(get_depenses_total(queryset), Decimal("40.00"))

    def test_depenses_kpis_return_today_month_average_and_evolution(self):
        kpis = get_depenses_kpis(self.entreprise_a)
        self.assertEqual(kpis["count"], 1)
        self.assertEqual(kpis["total"], Decimal("40.00"))
        self.assertEqual(kpis["today_total"], Decimal("40.00"))
        self.assertEqual(kpis["month_total"], Decimal("40.00"))
        self.assertEqual(kpis["average"], Decimal("40.00"))
        self.assertTrue(kpis["evolution_display"])

    def test_currency_helper_formats_thousands_with_spaces(self):
        self.entreprise_a.devise = "CDF"
        self.assertEqual(format_decimal_number(Decimal("1000")), "1 000,00")
        self.assertEqual(format_decimal_number(Decimal("1000000.50")), "1 000 000,50")
        self.assertEqual(format_amount_for_entreprise(Decimal("1000000.50"), self.entreprise_a), "1 000 000,50 CDF")

    def test_depenses_pdf_uses_shared_renderer_successfully(self):
        self.client.force_login(self.comptable_a)
        response = self.client.get(reverse("depenses_pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_depenses_page_displays_total_and_empty_state(self):
        empty_entreprise = create_entreprise("Entreprise Depenses Vide")
        empty_user = create_user("gestion-dep-empty", "gestionnaire", empty_entreprise)
        start_trial_for_entreprise(entreprise=empty_entreprise, plan=self.plan, utilisateur=empty_user)
        self.client.force_login(empty_user)
        response = self.client.get(reverse("depenses"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucune depense enregistree pour le moment")
        self.assertContains(response, "Ajouter une depense")

    def test_depenses_page_filters_by_search(self):
        self.client.force_login(self.gestionnaire_a)
        response = self.client.get(reverse("depenses"), {"q": "Papeterie"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Papeterie")
        self.assertNotContains(response, "Transport")
        self.assertContains(response, "Depenses du mois")
        self.assertContains(response, "Moyenne par depense")

    def test_comptable_cannot_see_add_depense_ui(self):
        self.client.force_login(self.comptable_a)
        response = self.client.get(reverse("depenses"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Ajouter une depense")
        self.assertContains(response, "Filtres et export")
