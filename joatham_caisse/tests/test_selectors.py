from decimal import Decimal

from django.test import TestCase

from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_caisse.models import Caisse
from joatham_caisse.selectors.caisse import get_caisses_by_entreprise
from joatham_caisse.selectors.session import get_open_session_for_caisse, get_sessions_by_entreprise
from joatham_caisse.services.session import open_session


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
