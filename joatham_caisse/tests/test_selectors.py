from decimal import Decimal

from django.test import TestCase

from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_caisse.models import Caisse
from joatham_caisse.selectors.caisse import get_caisses_by_entreprise
from joatham_caisse.selectors.mouvements import get_mouvements_for_entreprise
from joatham_caisse.selectors.session import get_open_session_for_caisse, get_sessions_by_entreprise
from joatham_caisse.services.mouvements import (
    record_cash_entry,
    record_cash_expense,
    record_cash_exit,
    record_invoice_cash_payment,
)
from joatham_caisse.services.session import close_session, open_session
from joatham_caisse.services.validation import validate_session


class CaisseSelectorsTests(TestCase):
    def setUp(self):
        self.entreprise_a = create_entreprise("Entreprise A")
        self.entreprise_b = create_entreprise("Entreprise B")
        self.owner_a = create_user("owner-a", "proprietaire", self.entreprise_a)
        self.owner_b = create_user("owner-b", "proprietaire", self.entreprise_b)
        self.caisse_a = Caisse.objects.create(
            entreprise=self.entreprise_a,
            nom="Caisse A",
            code="A-1",
            cree_par=self.owner_a,
        )
        self.caisse_b = Caisse.objects.create(
            entreprise=self.entreprise_b,
            nom="Caisse B",
            code="B-1",
            cree_par=self.owner_b,
        )

    def test_cashboxes_are_scoped_to_entreprise(self):
        results = list(get_caisses_by_entreprise(self.entreprise_a))
        self.assertEqual([item.id for item in results], [self.caisse_a.id])

    def test_open_session_selector_returns_only_current_company_session(self):
        session = open_session(
            entreprise=self.entreprise_a,
            caisse=self.caisse_a,
            utilisateur=self.owner_a,
            solde_initial=Decimal("10.00"),
        )
        self.assertEqual(get_open_session_for_caisse(self.caisse_a).id, session.id)
        self.assertEqual(len(list(get_sessions_by_entreprise(self.entreprise_a, caisse=self.caisse_a))), 1)
        self.assertEqual(len(list(get_sessions_by_entreprise(self.entreprise_b, caisse=self.caisse_b))), 0)


class CaisseFilterSelectorsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Selecteurs Caisse")
        self.autre_entreprise = create_entreprise("Entreprise Externe Caisse")
        self.owner = create_user("owner-selecteurs", "proprietaire", self.entreprise)
        self.second_user = create_user("cash-user-2", "gestionnaire", self.entreprise)
        self.other_owner = create_user("owner-selecteurs-b", "proprietaire", self.autre_entreprise)
        self.caisse = Caisse.objects.create(
            entreprise=self.entreprise,
            nom="Caisse principale",
            code="SEL-001",
            devise="CDF",
            cree_par=self.owner,
        )
        self.other_caisse = Caisse.objects.create(
            entreprise=self.autre_entreprise,
            nom="Caisse externe",
            code="SEL-EXT",
            devise="CDF",
            cree_par=self.other_owner,
        )
        self.open_session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )
        self.closed_session = open_session(
            entreprise=self.entreprise,
            caisse=Caisse.objects.create(
                entreprise=self.entreprise,
                nom="Caisse secondaire",
                code="SEL-002",
                devise="CDF",
                cree_par=self.second_user,
            ),
            utilisateur=self.second_user,
            solde_initial=Decimal("50.00"),
        )
        record_cash_entry(
            entreprise=self.entreprise,
            caisse=self.closed_session.caisse,
            session=self.closed_session,
            montant=Decimal("10.00"),
            libelle="Entree secondaire",
            utilisateur=self.second_user,
        )
        close_session(
            entreprise=self.entreprise,
            session=self.closed_session,
            utilisateur=self.second_user,
            solde_reel=Decimal("55.00"),
        )
        validate_session(
            entreprise=self.entreprise,
            session=self.closed_session,
            utilisateur=self.owner,
        )
        self.closed_session.refresh_from_db()

    def test_session_selector_filters_by_status(self):
        sessions = list(get_sessions_by_entreprise(self.entreprise, statut="validee"))
        self.assertEqual([item.id for item in sessions], [self.closed_session.id])

    def test_session_selector_filters_by_opening_user(self):
        sessions = list(get_sessions_by_entreprise(self.entreprise, utilisateur_ouverture=self.second_user))
        self.assertEqual([item.id for item in sessions], [self.closed_session.id])

    def test_session_selector_filters_sessions_with_ecart_only(self):
        sessions = list(get_sessions_by_entreprise(self.entreprise, avec_ecart=True))
        self.assertEqual([item.id for item in sessions], [self.closed_session.id])

    def test_movement_selector_filters_by_type(self):
        entry = record_cash_entry(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.open_session,
            montant=Decimal("20.00"),
            libelle="Entree journal",
            utilisateur=self.owner,
        )
        record_cash_exit(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.open_session,
            montant=Decimal("5.00"),
            libelle="Sortie journal",
            utilisateur=self.owner,
        )
        movements = list(get_mouvements_for_entreprise(self.entreprise, caisse=self.caisse, type_mouvement="entree"))
        self.assertEqual([item.id for item in movements], [entry.id])

    def test_movement_selector_filters_by_amount_range(self):
        low = record_cash_entry(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.open_session,
            montant=Decimal("15.00"),
            libelle="Petit encaissement",
            utilisateur=self.owner,
        )
        high = record_cash_entry(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.open_session,
            montant=Decimal("60.00"),
            libelle="Gros encaissement",
            utilisateur=self.owner,
        )
        movements = list(
            get_mouvements_for_entreprise(
                self.entreprise,
                montant_min=Decimal("20.00"),
                montant_max=Decimal("100.00"),
            )
        )
        self.assertEqual([item.id for item in movements], [high.id])
        self.assertNotIn(low.id, [item.id for item in movements])

    def test_movement_selector_searches_by_label_and_reference(self):
        by_label = record_cash_expense(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.open_session,
            montant=Decimal("12.00"),
            libelle="Achat papier",
            utilisateur=self.owner,
        )
        by_reference = record_invoice_cash_payment(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.open_session,
            montant=Decimal("40.00"),
            libelle="Paiement facture #F-001",
            reference="PAY-TEST-001",
            utilisateur=self.owner,
        )
        movements = list(get_mouvements_for_entreprise(self.entreprise, q="papier"))
        self.assertEqual([item.id for item in movements], [by_label.id])
        movements = list(get_mouvements_for_entreprise(self.entreprise, q="PAY-TEST-001"))
        self.assertEqual([item.id for item in movements], [by_reference.id])

    def test_movement_selector_stays_scoped_to_entreprise(self):
        external_session = open_session(
            entreprise=self.autre_entreprise,
            caisse=self.other_caisse,
            utilisateur=self.other_owner,
            solde_initial=Decimal("90.00"),
        )
        record_cash_entry(
            entreprise=self.autre_entreprise,
            caisse=self.other_caisse,
            session=external_session,
            montant=Decimal("25.00"),
            libelle="Encaissement externe",
            utilisateur=self.other_owner,
        )
        movements = list(get_mouvements_for_entreprise(self.entreprise))
        self.assertTrue(all(item.entreprise_id == self.entreprise.id for item in movements))
