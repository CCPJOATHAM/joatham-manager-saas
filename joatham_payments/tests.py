from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from core.models import ActivityLog
from core.services.subscription import (
    FREE_PLAN_MODULES,
    PREMIUM_PLAN_MODULES,
    PRO_PLAN_MODULES,
    STARTER_PLAN_MODULES,
    activate_free_plan_for_entreprise,
    activate_subscription_for_entreprise,
    get_default_paid_plans,
    get_or_create_free_plan,
)
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
        premium_payload = next(plan for plan in get_default_paid_plans() if plan["code"] == "premium")
        self.plan_premium = Abonnement.objects.create(**premium_payload, actif=True)
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.plan_premium, utilisateur=self.owner)
        activate_subscription_for_entreprise(entreprise=self.other_entreprise, plan=self.plan_premium, utilisateur=self.other_owner)
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

    def _create_official_plan(self, code):
        payload = next(plan for plan in get_default_paid_plans() if plan["code"] == code)
        return Abonnement.objects.create(**payload, actif=True)

    def _assert_payments_module_blocked_for_plan(self, *, plan_code, expected_reason):
        entreprise = create_entreprise(f"Entreprise {plan_code} Paiements")
        owner = create_user(f"owner-{plan_code}-payments", "proprietaire", entreprise)
        if plan_code == "free":
            plan = get_or_create_free_plan()
            activate_free_plan_for_entreprise(entreprise=entreprise, plan=plan, utilisateur=owner)
        else:
            plan = self._create_official_plan(plan_code)
            activate_subscription_for_entreprise(entreprise=entreprise, plan=plan, utilisateur=owner)

        self.client.force_login(owner)
        response = self.client.get(reverse("payment_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("module=payments", response["Location"])
        self.assertIn(f"reason={expected_reason}", response["Location"])

    def test_free_starter_and_pro_plans_block_payments_module(self):
        self._assert_payments_module_blocked_for_plan(plan_code="free", expected_reason="premium_required")
        self._assert_payments_module_blocked_for_plan(plan_code="starter", expected_reason="premium_required")
        self._assert_payments_module_blocked_for_plan(plan_code="pro", expected_reason="premium_required")

    def test_premium_plan_allows_payments_views_and_exports(self):
        payment = create_payment_transaction(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.CASH,
            amount=Decimal("10.00"),
            utilisateur=self.gestionnaire,
        )
        self.client.force_login(self.owner)

        self.assertEqual(self.client.get(reverse("payment_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("payment_create")).status_code, 200)
        self.assertEqual(self.client.get(reverse("payment_reports")).status_code, 200)
        self.assertEqual(self.client.get(reverse("payment_export_excel")).status_code, 200)

        confirm_response = self.client.post(reverse("payment_confirm", args=[payment.id]))
        self.assertEqual(confirm_response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentTransaction.Status.CONFIRME)

    def test_navigation_locks_payments_for_pro_and_links_it_for_premium(self):
        pro_entreprise = create_entreprise("Entreprise Pro Navigation Paiements")
        pro_owner = create_user("owner-pro-nav-payments", "proprietaire", pro_entreprise)
        pro_plan = self._create_official_plan("pro")
        activate_subscription_for_entreprise(entreprise=pro_entreprise, plan=pro_plan, utilisateur=pro_owner)

        self.client.force_login(pro_owner)
        pro_response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(pro_response, "Paiements")
        self.assertContains(pro_response, "Premium")
        self.assertNotContains(pro_response, reverse("payment_list"))

        self.client.force_login(self.owner)
        premium_response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(premium_response, reverse("payment_list"))

    def test_default_plan_payloads_keep_payments_premium_only(self):
        payment_modules = {
            "payments",
            "paiements",
            "mobile_money",
            "payment_validation",
            "payments_reports",
            "payments_exports",
        }

        self.assertTrue(payment_modules.isdisjoint(FREE_PLAN_MODULES))
        self.assertTrue(payment_modules.isdisjoint(STARTER_PLAN_MODULES))
        self.assertTrue(payment_modules.isdisjoint(PRO_PLAN_MODULES))
        self.assertTrue(payment_modules.issubset(PREMIUM_PLAN_MODULES))
