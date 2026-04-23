from decimal import Decimal

from django.test import TestCase

from joatham_comptabilite.models import CompteComptable, EcritureComptable, JournalComptable
from joatham_comptabilite.services.bootstrap import bootstrap_comptabilite_entreprise
from joatham_comptabilite.services.comptabilisation import (
    comptabiliser_depense,
    comptabiliser_facture_emise,
    comptabiliser_paiement_facture,
)

from .factories import create_depense, create_entreprise, create_facture_and_payment, create_user


class ComptabilisationTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise()
        self.gestionnaire = create_user("gest-compta", "gestionnaire", self.entreprise)
        self.comptable = create_user("comp-compta", "comptable", self.entreprise)

    def test_bootstrap_creates_chart_and_journals(self):
        bootstrap_comptabilite_entreprise(self.entreprise)
        self.assertTrue(CompteComptable.objects.filter(entreprise=self.entreprise, numero="411").exists())
        self.assertTrue(JournalComptable.objects.filter(entreprise=self.entreprise, code="JV").exists())

    def test_facture_entry_is_balanced_and_idempotent(self):
        facture, _ = create_facture_and_payment(self.entreprise, self.gestionnaire, self.comptable)
        ecriture = comptabiliser_facture_emise(facture)
        duplicate = comptabiliser_facture_emise(facture)

        self.assertEqual(ecriture.id, duplicate.id)
        self.assertTrue(ecriture.est_equilibree())
        self.assertEqual(
            EcritureComptable.objects.filter(
                entreprise=self.entreprise,
                source_app="joatham_billing",
                source_model="Facture",
                source_id=facture.id,
                source_event="facture_emise",
            ).count(),
            1,
        )

    def test_payment_entry_is_balanced_and_idempotent(self):
        facture, paiement = create_facture_and_payment(self.entreprise, self.gestionnaire, self.comptable)
        ecriture = comptabiliser_paiement_facture(paiement)
        duplicate = comptabiliser_paiement_facture(paiement)

        self.assertEqual(ecriture.id, duplicate.id)
        self.assertTrue(ecriture.est_equilibree())

    def test_depense_entry_is_balanced_and_idempotent(self):
        depense = create_depense(self.entreprise)
        ecriture = comptabiliser_depense(depense)
        duplicate = comptabiliser_depense(depense)

        self.assertEqual(ecriture.id, duplicate.id)
        self.assertTrue(ecriture.est_equilibree())

    def test_multi_entreprise_isolation(self):
        entreprise_b = create_entreprise("Entreprise B")
        gestionnaire_b = create_user("gest-b", "gestionnaire", entreprise_b)
        comptable_b = create_user("comp-b", "comptable", entreprise_b)
        facture_a, _ = create_facture_and_payment(self.entreprise, self.gestionnaire, self.comptable)
        facture_b, _ = create_facture_and_payment(entreprise_b, gestionnaire_b, comptable_b)

        self.assertTrue(EcritureComptable.objects.filter(entreprise=self.entreprise, source_id=facture_a.id).exists())
        self.assertTrue(EcritureComptable.objects.filter(entreprise=entreprise_b, source_id=facture_b.id).exists())
        self.assertFalse(EcritureComptable.objects.filter(entreprise=self.entreprise, source_id=facture_b.id).exists())
