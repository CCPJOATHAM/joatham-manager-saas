from decimal import Decimal

from django.http import Http404
from django.test import TestCase

from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_caisse.models import Caisse, MouvementCaisse, SessionCaisse, ValidationCaisse
from joatham_caisse.selectors.mouvements import get_cash_flow_totals_for_session
from joatham_caisse.services.caisse import create_caisse, deactivate_caisse
from joatham_caisse.services.mouvements import record_cash_entry, record_cash_exit, record_mouvement
from joatham_caisse.services.session import close_session, compute_theoretical_balance, open_session
from joatham_caisse.services.validation import reject_session, validate_session


class CaisseServicesTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Caisse Service")
        self.autre_entreprise = create_entreprise("Entreprise Caisse Service B")
        self.owner = create_user("owner-caisse-service", "proprietaire", self.entreprise)
        self.other_owner = create_user("owner-caisse-service-b", "proprietaire", self.autre_entreprise)
        self.caisse = Caisse.objects.create(
            entreprise=self.entreprise,
            nom="Caisse principale",
            code="CAISSE-001",
            devise="CDF",
            cree_par=self.owner,
        )

    def test_create_caisse_service_creates_cashbox(self):
        caisse = create_caisse(
            entreprise=self.entreprise,
            nom="Caisse secondaire",
            code="CAISSE-002",
            devise="USD",
            utilisateur=self.owner,
        )
        self.assertEqual(caisse.entreprise, self.entreprise)
        self.assertEqual(caisse.code, "CAISSE-002")

    def test_create_caisse_rejects_blank_name_or_code(self):
        invalid_payloads = [
            {"nom": "   ", "code": "CAISSE-BLANK-NAME"},
            {"nom": "Caisse sans code", "code": "   "},
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    create_caisse(
                        entreprise=self.entreprise,
                        devise="CDF",
                        utilisateur=self.owner,
                        **payload,
                    )

        self.assertFalse(Caisse.objects.filter(entreprise=self.entreprise, code__in=["CAISSE-BLANK-NAME", ""]).exists())

    def test_open_session_rejects_negative_initial_balance(self):
        with self.assertRaises(ValueError):
            open_session(
                entreprise=self.entreprise,
                caisse=self.caisse,
                utilisateur=self.owner,
                solde_initial=Decimal("-1.00"),
            )

        self.assertEqual(self.caisse.sessions.count(), 0)

    def test_open_session_blocks_double_opening(self):
        open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )

        with self.assertRaises(ValueError):
            open_session(
                entreprise=self.entreprise,
                caisse=self.caisse,
                utilisateur=self.owner,
                solde_initial=Decimal("50.00"),
            )

    def test_record_movement_is_blocked_when_session_is_closed(self):
        session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )
        close_session(
            entreprise=self.entreprise,
            session=session,
            utilisateur=self.owner,
            solde_reel=Decimal("100.00"),
        )

        with self.assertRaises(ValueError):
            record_cash_entry(
                entreprise=self.entreprise,
                caisse=self.caisse,
                session=session,
                montant=Decimal("10.00"),
                libelle="Entree tardive",
                utilisateur=self.owner,
            )

    def test_record_movement_rejects_non_positive_amounts(self):
        session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )

        for invalid_amount in (Decimal("0.00"), Decimal("-5.00")):
            with self.subTest(invalid_amount=invalid_amount):
                with self.assertRaises(ValueError):
                    record_cash_entry(
                        entreprise=self.entreprise,
                        caisse=self.caisse,
                        session=session,
                        montant=invalid_amount,
                        libelle="Montant invalide",
                        utilisateur=self.owner,
                    )
                with self.assertRaises(ValueError):
                    record_cash_exit(
                        entreprise=self.entreprise,
                        caisse=self.caisse,
                        session=session,
                        montant=invalid_amount,
                        libelle="Montant invalide",
                        utilisateur=self.owner,
                    )

        self.assertEqual(MouvementCaisse.objects.filter(session=session).count(), 0)

    def test_record_movement_rejects_invalid_type_and_blank_label(self):
        session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )

        with self.assertRaises(ValueError):
            record_mouvement(
                entreprise=self.entreprise,
                caisse=self.caisse,
                session=session,
                type_mouvement="type_inconnu",
                montant=Decimal("10.00"),
                libelle="Mouvement invalide",
                utilisateur=self.owner,
            )
        with self.assertRaises(ValueError):
            record_cash_entry(
                entreprise=self.entreprise,
                caisse=self.caisse,
                session=session,
                montant=Decimal("10.00"),
                libelle="   ",
                utilisateur=self.owner,
            )

        self.assertEqual(MouvementCaisse.objects.filter(session=session).count(), 0)

    def test_wrong_tenant_is_blocked(self):
        session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )

        with self.assertRaises(Http404):
            record_cash_exit(
                entreprise=self.autre_entreprise,
                caisse=self.caisse,
                session=session,
                montant=Decimal("10.00"),
                libelle="Sortie cross-tenant",
                utilisateur=self.other_owner,
            )

    def test_close_session_computes_theoretical_balance(self):
        session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )
        record_cash_entry(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=session,
            montant=Decimal("50.00"),
            libelle="Vente cash",
            utilisateur=self.owner,
        )
        record_cash_exit(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=session,
            montant=Decimal("20.00"),
            libelle="Sortie",
            utilisateur=self.owner,
        )

        self.assertEqual(compute_theoretical_balance(session), Decimal("130.00"))
        close_session(
            entreprise=self.entreprise,
            session=session,
            utilisateur=self.owner,
            solde_reel=Decimal("128.00"),
        )
        session.refresh_from_db()
        self.assertEqual(session.solde_theorique, Decimal("130.00"))
        self.assertEqual(session.ecart, Decimal("-2.00"))

    def test_close_session_rejects_negative_real_balance(self):
        session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )

        with self.assertRaises(ValueError):
            close_session(
                entreprise=self.entreprise,
                session=session,
                utilisateur=self.owner,
                solde_reel=Decimal("-1.00"),
            )

        session.refresh_from_db()
        self.assertEqual(session.statut, SessionCaisse.Statut.OUVERTE)
        self.assertIsNone(session.solde_reel)

    def test_validation_is_allowed_only_after_closing(self):
        session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )

        with self.assertRaises(ValueError):
            validate_session(
                entreprise=self.entreprise,
                session=session,
                utilisateur=self.owner,
            )

    def test_validation_cannot_happen_twice(self):
        session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )
        close_session(
            entreprise=self.entreprise,
            session=session,
            utilisateur=self.owner,
            solde_reel=Decimal("100.00"),
        )

        validate_session(entreprise=self.entreprise, session=session, utilisateur=self.owner)
        with self.assertRaises(ValueError):
            validate_session(entreprise=self.entreprise, session=session, utilisateur=self.owner)

    def test_reject_session_creates_rejected_validation(self):
        session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )
        close_session(
            entreprise=self.entreprise,
            session=session,
            utilisateur=self.owner,
            solde_reel=Decimal("99.00"),
        )

        validation = reject_session(
            entreprise=self.entreprise,
            session=session,
            utilisateur=self.owner,
            commentaire="Ecart a verifier",
        )
        self.assertEqual(validation.decision, ValidationCaisse.Decision.REJETEE)
        self.assertEqual(session.validations.count(), 1)

    def test_deactivate_cashbox_is_blocked_when_session_is_open(self):
        open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )
        with self.assertRaises(ValueError):
            deactivate_caisse(entreprise=self.entreprise, caisse=self.caisse, utilisateur=self.owner)


class CaisseSelectorHelpersTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Caisse Totaux")
        self.owner = create_user("owner-caisse-totaux", "proprietaire", self.entreprise)
        self.caisse = Caisse.objects.create(
            entreprise=self.entreprise,
            nom="Caisse principale",
            code="CAISSE-TOTAL",
            devise="CDF",
            cree_par=self.owner,
        )
        self.session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("50.00"),
        )

    def test_cash_flow_totals_are_split_by_entries_and_exits(self):
        record_cash_entry(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.session,
            montant=Decimal("20.00"),
            libelle="Entree",
            utilisateur=self.owner,
        )
        record_cash_exit(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.session,
            montant=Decimal("10.00"),
            libelle="Sortie",
            utilisateur=self.owner,
        )

        totals = get_cash_flow_totals_for_session(self.session)
        self.assertEqual(totals["total_entrees"], Decimal("20.00"))
        self.assertEqual(totals["total_sorties"], Decimal("10.00"))
        self.assertEqual(MouvementCaisse.objects.filter(session=self.session).count(), 2)
