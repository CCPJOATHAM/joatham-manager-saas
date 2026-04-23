from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.services.subscription import activate_subscription_for_entreprise
from joatham_comptabilite.selectors.comptabilite import (
    get_comptes_by_entreprise,
    get_ecritures_by_entreprise,
    get_entreprises_for_accounting_user,
    get_exercices_by_entreprise,
    get_journaux_by_entreprise,
    get_lignes_ecriture_by_entreprise,
)
from joatham_comptabilite.services.reporting import build_balance, build_bilan_simplifie, build_compte_resultat, build_grand_livre
from joatham_users.models import Abonnement

from .factories import create_depense, create_entreprise, create_facture_and_payment, create_user


class ReportingServiceTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Reporting")
        self.gestionnaire = create_user("gest-reporting", "gestionnaire", self.entreprise)
        self.comptable = create_user("comp-reporting", "comptable", self.entreprise)
        self.plan = Abonnement.objects.create(nom="Accounting", code="accounting", prix=39, duree_jours=30, actif=True)
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.gestionnaire)
        create_facture_and_payment(self.entreprise, self.gestionnaire, self.comptable)
        create_depense(self.entreprise, montant=Decimal("25"))

    def test_build_balance_returns_balanced_totals(self):
        report = build_balance(self.entreprise)

        self.assertEqual(report["total_debit"], Decimal("191.00"))
        self.assertEqual(report["total_credit"], Decimal("191.00"))
        self.assertTrue(any(row["numero"] == "411" for row in report["rows"]))

    def test_build_grand_livre_returns_running_balances(self):
        report = build_grand_livre(self.entreprise)
        client_account = next(account for account in report["accounts"] if account["numero"] == "411")

        self.assertEqual(client_account["total_debit"], Decimal("116.00"))
        self.assertEqual(client_account["total_credit"], Decimal("50.00"))
        self.assertEqual(client_account["solde_debit"], Decimal("66.00"))
        self.assertEqual(client_account["solde_credit"], Decimal("0.00"))
        self.assertEqual(len(client_account["lignes"]), 2)

    def test_build_compte_resultat_returns_expected_net_income(self):
        report = build_compte_resultat(self.entreprise)

        self.assertEqual(report["total_produits"], Decimal("100.00"))
        self.assertEqual(report["total_charges"], Decimal("25.00"))
        self.assertEqual(report["resultat_net"], Decimal("75.00"))

    def test_build_bilan_simplifie_uses_result_in_passif(self):
        report = build_bilan_simplifie(self.entreprise)

        self.assertEqual(report["actif"], Decimal("91.00"))
        self.assertEqual(report["passif"], Decimal("91.00"))
        self.assertTrue(report["equilibre"])

    def test_comptabilite_selectors_are_scoped_to_entreprise(self):
        entreprise_b = create_entreprise("Entreprise Reporting B")
        gestionnaire_b = create_user("gest-reporting-b", "gestionnaire", entreprise_b)
        comptable_b = create_user("comp-reporting-b", "comptable", entreprise_b)
        create_facture_and_payment(entreprise_b, gestionnaire_b, comptable_b)

        self.assertTrue(get_comptes_by_entreprise(self.entreprise).exists())
        self.assertTrue(get_journaux_by_entreprise(self.entreprise).exists())
        self.assertTrue(get_exercices_by_entreprise(self.entreprise).exists())
        self.assertEqual(get_entreprises_for_accounting_user(self.gestionnaire).count(), 1)
        self.assertTrue(all(e.entreprise_id == self.entreprise.id for e in get_ecritures_by_entreprise(self.entreprise)))
        self.assertTrue(all(l.ecriture.entreprise_id == self.entreprise.id for l in get_lignes_ecriture_by_entreprise(self.entreprise)))

    def test_comptabilite_views_still_render_with_refactored_reads(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("balance"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "411")
