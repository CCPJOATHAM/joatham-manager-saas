from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_caisse.models import Caisse, MouvementCaisse, SessionCaisse, ValidationCaisse


class CaisseModelsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Caisse A")
        self.autre_entreprise = create_entreprise("Entreprise Caisse B")
        self.owner = create_user("owner-caisse", "proprietaire", self.entreprise)
        self.caisse = Caisse.objects.create(
            entreprise=self.entreprise,
            nom="Caisse principale",
            code="CS-001",
            devise="CDF",
            cree_par=self.owner,
        )

    def test_code_must_be_unique_per_entreprise(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Caisse.objects.create(
                    entreprise=self.entreprise,
                    nom="Caisse secondaire",
                    code="CS-001",
                )

        other = Caisse.objects.create(
            entreprise=self.autre_entreprise,
            nom="Caisse externe",
            code="CS-001",
        )
        self.assertIsNotNone(other.pk)

    def test_only_one_open_session_per_caisse(self):
        SessionCaisse.objects.create(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur_ouverture=self.owner,
            solde_initial=Decimal("10.00"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SessionCaisse.objects.create(
                    entreprise=self.entreprise,
                    caisse=self.caisse,
                    utilisateur_ouverture=self.owner,
                    solde_initial=Decimal("5.00"),
                )

    def test_movement_amount_must_be_strictly_positive(self):
        session = SessionCaisse.objects.create(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur_ouverture=self.owner,
            solde_initial=Decimal("10.00"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MouvementCaisse.objects.create(
                    entreprise=self.entreprise,
                    caisse=self.caisse,
                    session=session,
                    type_mouvement=MouvementCaisse.TypeMouvement.ENTREE,
                    montant=Decimal("0.00"),
                    libelle="Test",
                )

    def test_only_one_validation_is_allowed_per_session(self):
        session = SessionCaisse.objects.create(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur_ouverture=self.owner,
            solde_initial=Decimal("10.00"),
            statut=SessionCaisse.Statut.FERMEE,
        )
        ValidationCaisse.objects.create(
            entreprise=self.entreprise,
            session=session,
            validee_par=self.owner,
            decision=ValidationCaisse.Decision.VALIDEE,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ValidationCaisse.objects.create(
                    entreprise=self.entreprise,
                    session=session,
                    validee_par=self.owner,
                    decision=ValidationCaisse.Decision.REJETEE,
                )
