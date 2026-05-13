from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from core.models import ActivityLog
from core.services.subscription import activate_free_plan_for_entreprise, activate_subscription_for_entreprise, get_default_paid_plans, get_or_create_free_plan
from joatham_billing.models import Facture, PaiementFacture
from joatham_billing.tests.factories import create_entreprise, create_facture_sample, create_user
from joatham_caisse.models import Caisse, MouvementCaisse
from joatham_caisse.services.session import open_session
from joatham_users.models import Abonnement

from .models import PaymentTransaction
from .selectors.payments import get_payment_transactions_for_entreprise
from .services.payments import (
    PaymentOperationError,
    cancel_payment_transaction,
    confirm_payment_transaction,
    create_payment_transaction,
    reject_payment_transaction,
)


class PaymentTransactionTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Paiements")
        self.other_entreprise = create_entreprise("Entreprise Paiements B")
        self.owner = create_user("owner-payments", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("manager-payments", "gestionnaire", self.entreprise)
        self.comptable = create_user("accountant-payments", "comptable", self.entreprise)
        self.other_owner = create_user("owner-payments-b", "proprietaire", self.other_entreprise)
        pro_payload = next(plan for plan in get_default_paid_plans() if plan["code"] == "pro")
        self.plan_pro = Abonnement.objects.create(**pro_payload, actif=True)
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.plan_pro, utilisateur=self.owner)
        activate_subscription_for_entreprise(entreprise=self.other_entreprise, plan=self.plan_pro, utilisateur=self.other_owner)
        self.caisse = Caisse.objects.create(
            entreprise=self.entreprise,
            nom="Caisse principale",
            code="CAISSE-PAY",
            devise="CDF",
            cree_par=self.owner,
        )
        self.session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("0.00"),
        )

    def test_create_cash_payment(self):
        payment = create_payment_transaction(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.CASH,
            amount=Decimal("25.00"),
            caisse=self.caisse,
            session_caisse=self.session,
            reference="CASH-001",
            utilisateur=self.gestionnaire,
        )

        self.assertEqual(payment.status, PaymentTransaction.Status.EN_ATTENTE)
        self.assertEqual(payment.method, PaymentTransaction.Method.CASH)
        self.assertEqual(payment.created_by, self.gestionnaire)

    def test_create_mobile_money_payment(self):
        payment = create_payment_transaction(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.MPESA,
            amount=Decimal("45.00"),
            reference="MPESA-001",
            phone_number="+243970000000",
            mobile_operator=PaymentTransaction.MobileOperator.MPESA,
            utilisateur=self.gestionnaire,
        )

        self.assertTrue(payment.is_mobile_money)
        self.assertEqual(payment.phone_number, "+243970000000")
        self.assertEqual(payment.mobile_operator, PaymentTransaction.MobileOperator.MPESA)

    def test_confirmed_invoice_payment_updates_invoice(self):
        facture = create_facture_sample(self.entreprise, self.gestionnaire, montant=Decimal("100"))
        amount_due = facture.reste_a_payer

        payment = create_payment_transaction(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.MPESA,
            amount=amount_due,
            facture=facture,
            reference="MPESA-FAC-001",
            utilisateur=self.owner,
            status=PaymentTransaction.Status.CONFIRME,
        )

        facture.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentTransaction.Status.CONFIRME)
        self.assertEqual(facture.statut, Facture.Statut.PAYEE)
        self.assertTrue(facture.paye)
        self.assertEqual(payment.paiement_facture.mode, PaiementFacture.ModePaiement.MPESA)

    def test_confirmed_cash_payment_creates_cash_movement(self):
        payment = create_payment_transaction(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.CASH,
            amount=Decimal("30.00"),
            caisse=self.caisse,
            session_caisse=self.session,
            reference="CASH-MOVE-001",
            utilisateur=self.owner,
            status=PaymentTransaction.Status.CONFIRME,
        )

        payment.refresh_from_db()
        self.assertIsNotNone(payment.mouvement_caisse)
        self.assertEqual(payment.mouvement_caisse.type_mouvement, MouvementCaisse.TypeMouvement.ENTREE)
        self.assertEqual(payment.mouvement_caisse.moyen_paiement, PaymentTransaction.Method.CASH)

    def test_rejected_payment_does_not_modify_invoice(self):
        facture = create_facture_sample(self.entreprise, self.gestionnaire, montant=Decimal("50"))
        payment = create_payment_transaction(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.BANK_TRANSFER,
            amount=Decimal("10.00"),
            facture=facture,
            reference="BANK-PENDING",
            utilisateur=self.gestionnaire,
        )

        reject_payment_transaction(transaction_obj=payment, utilisateur=self.comptable, note="Reference non retrouvee")
        facture.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentTransaction.Status.REJETE)
        self.assertEqual(facture.statut, Facture.Statut.EMISE)
        self.assertFalse(facture.paye)
        self.assertFalse(PaiementFacture.objects.filter(facture=facture).exists())

    def test_cancel_payment_is_audited(self):
        payment = create_payment_transaction(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.CARD,
            amount=Decimal("20.00"),
            reference="CARD-CANCEL",
            utilisateur=self.gestionnaire,
        )

        cancel_payment_transaction(transaction_obj=payment, utilisateur=self.owner, note="Doublon")
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentTransaction.Status.ANNULE)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                action="payment_transaction_cancelled",
                objet_id=payment.id,
            ).exists()
        )

    def test_confirmed_invoice_payment_cannot_be_cancelled_directly(self):
        facture = create_facture_sample(self.entreprise, self.gestionnaire, montant=Decimal("30"))
        payment = create_payment_transaction(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.MPESA,
            amount=facture.reste_a_payer,
            facture=facture,
            utilisateur=self.owner,
            status=PaymentTransaction.Status.CONFIRME,
        )

        with self.assertRaises(PaymentOperationError):
            cancel_payment_transaction(transaction_obj=payment, utilisateur=self.owner, note="Annulation interdite")

    def test_multi_tenant_isolation(self):
        own_payment = create_payment_transaction(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.CASH,
            amount=Decimal("10.00"),
            utilisateur=self.gestionnaire,
        )
        other_payment = create_payment_transaction(
            entreprise=self.other_entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.CASH,
            amount=Decimal("15.00"),
            utilisateur=self.other_owner,
        )

        queryset = get_payment_transactions_for_entreprise(self.entreprise)
        self.assertIn(own_payment, queryset)
        self.assertNotIn(other_payment, queryset)

    def test_permissions_by_role(self):
        with self.assertRaises(PermissionDenied):
            create_payment_transaction(
                entreprise=self.entreprise,
                transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
                method=PaymentTransaction.Method.CASH,
                amount=Decimal("10.00"),
                utilisateur=self.comptable,
            )

        payment = create_payment_transaction(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.CASH,
            amount=Decimal("10.00"),
            utilisateur=self.gestionnaire,
        )
        confirmed = confirm_payment_transaction(transaction_obj=payment, utilisateur=self.comptable)
        self.assertEqual(confirmed.status, PaymentTransaction.Status.CONFIRME)

    def test_plan_access_blocks_reports_on_free_plan(self):
        free_entreprise = create_entreprise("Entreprise Free Paiements")
        free_owner = create_user("owner-free-payments", "proprietaire", free_entreprise)
        free_plan = get_or_create_free_plan()
        activate_free_plan_for_entreprise(entreprise=free_entreprise, plan=free_plan, utilisateur=free_owner)

        self.client.force_login(free_owner)
        list_response = self.client.get(reverse("payment_list"))
        report_response = self.client.get(reverse("payment_reports"))

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(report_response.status_code, 302)
        self.assertIn("module=payments_reports", report_response["Location"])

