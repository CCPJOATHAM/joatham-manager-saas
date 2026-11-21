"""Payment transitions use mocked providers only: no real checkout or payment."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import close_old_connections, connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from core.forms import PaiementAbonnementForm, ManualSubscriptionPaymentForm
from core.models import PaiementAbonnement
from core.services.payment_providers import VerifiedWebhookPayment
from core.services.subscription import activate_subscription_for_entreprise, create_subscription_payment_request, validate_subscription_payment, refuse_subscription_payment
from core.services.subscription_payments import (
    apply_verified_subscription_payment, create_automatic_subscription_payment_request,
    reconcile_subscription_payment, resume_or_create_automatic_payment,
)
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement, AbonnementEntreprise


class PaymentFixtures:
    def setUp(self):
        self.company = create_entreprise("Entreprise Démo — données intactes")
        self.company.devise = "USD"
        self.company.save(update_fields=["devise"])
        self.owner = create_user("subscription-owner", "proprietaire", self.company)
        self.plan = Abonnement.objects.create(nom="Starter", code="starter", prix=10, duree_jours=30, actif=True)

    def payment(self, **kwargs):
        return create_automatic_subscription_payment_request(
            entreprise=self.company, plan=self.plan, duree=PaiementAbonnement.Duree.MENSUEL,
            provider="test", utilisateur=self.owner, **kwargs,
        )

    def verified(self, payment, status="paid", amount="10.00", currency="USD", event="transaction-1"):
        return VerifiedWebhookPayment(
            external_reference=payment.external_reference, event_id=event, status=status,
            amount=Decimal(amount), currency=currency, provider_transaction_id="transaction-1",
            provider_status=status, raw_payload={"status": status},
        )


@override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True)
class SubscriptionReliabilityTests(PaymentFixtures, TestCase):
    def test_same_transaction_pending_then_paid_is_not_discarded(self):
        payment = self.payment()
        pending = apply_verified_subscription_payment("test", self.verified(payment, "processing"))
        self.assertFalse(pending.activated)
        paid = apply_verified_subscription_payment("test", self.verified(payment))
        self.assertTrue(paid.activated)
        self.assertEqual(paid.paiement.statut, PaiementAbonnement.Statut.VALIDE)

    def test_paid_is_absorbing_even_after_late_failure_with_new_event(self):
        payment = self.payment()
        first = apply_verified_subscription_payment("test", self.verified(payment))
        end = AbonnementEntreprise.objects.get(entreprise=self.company).date_fin
        snapshot = (first.paiement.amount_paid, first.paiement.paid_currency, first.paiement.verified_at)
        for status in ("failed", "cancelled", "expired", "processing", "paid"):
            result = apply_verified_subscription_payment("test", self.verified(payment, status, "1.00", "EUR", event=status))
            self.assertTrue(result.duplicate)
            self.assertFalse(result.activated)
            self.assertEqual(result.paiement.statut, PaiementAbonnement.Statut.VALIDE)
            self.assertEqual((result.paiement.amount_paid, result.paiement.paid_currency, result.paiement.verified_at), snapshot)
        self.assertEqual(AbonnementEntreprise.objects.get(entreprise=self.company).date_fin, end)

    def test_wrong_currency_does_not_change_expected_currency_or_poison_retry(self):
        payment = self.payment()
        rejected = apply_verified_subscription_payment("test", self.verified(payment, currency="EUR"))
        self.assertTrue(rejected.rejected)
        payment.refresh_from_db()
        self.assertEqual(payment.paid_currency, "USD")
        self.assertIsNone(payment.amount_paid)
        accepted = apply_verified_subscription_payment("test", self.verified(payment))
        self.assertTrue(accepted.activated)

    def test_manual_approval_and_refusal_cannot_override_automatic_payment(self):
        payment = self.payment()
        for action in (validate_subscription_payment, refuse_subscription_payment):
            with self.assertRaises(ValueError):
                action(paiement=payment, super_admin=self.owner)
        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.company).exists())

    def test_stale_manual_approval_cannot_extend_twice(self):
        payment = create_subscription_payment_request(
            entreprise=self.company, plan=self.plan, duree="mensuel", reference_paiement="MOMO-1",
            methode_paiement=PaiementAbonnement.Methode.MOBILE_MONEY,
        )
        stale = PaiementAbonnement.objects.get(pk=payment.pk)
        first = validate_subscription_payment(paiement=payment, super_admin=self.owner)
        with self.assertRaises(ValueError):
            validate_subscription_payment(paiement=stale, super_admin=self.owner)
        self.assertEqual(AbonnementEntreprise.objects.get(pk=first.pk).date_fin, first.date_fin)

    def test_repeated_checkout_resumes_order_at_persisted_price(self):
        kwargs = dict(entreprise=self.company, plan=self.plan, duree="annuel", provider="test", utilisateur=self.owner)
        first = resume_or_create_automatic_payment(**kwargs)
        second = resume_or_create_automatic_payment(**kwargs)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.amount_expected, Decimal("96.00"))
        self.assertEqual(PaiementAbonnement.objects.filter(entreprise=self.company).count(), 1)

    def test_renewal_coverage_starts_at_previous_end(self):
        original_end = timezone.localdate() + timedelta(days=12)
        AbonnementEntreprise.objects.create(
            entreprise=self.company, plan=self.plan, statut="actif", actif=True,
            date_debut=timezone.localdate(), date_fin=original_end,
        )
        result = apply_verified_subscription_payment("test", self.verified(self.payment()))
        self.assertEqual(result.paiement.periode_debut, original_end)
        self.assertEqual(result.paiement.periode_fin, original_end + timedelta(days=30))

    def test_renewal_discards_stale_related_subscription_cache(self):
        first = activate_subscription_for_entreprise(entreprise=self.company, plan=self.plan, duration_days=30)
        # Populate the reverse relation cache, then change the row independently.
        self.company.abonnement_entreprise
        AbonnementEntreprise.objects.filter(pk=first.pk).update(date_fin=first.date_fin + timedelta(days=30))
        renewed = activate_subscription_for_entreprise(
            entreprise=self.company, plan=self.plan, duration_days=30, prolong_existing=True,
        )
        self.assertEqual(renewed.date_fin, first.date_fin + timedelta(days=60))

    def test_server_reconciliation_uses_provider_and_not_browser_status(self):
        payment = self.payment()
        payment.provider = "cinetpay"
        payment.provider_notify_token = "dummy-notify-token"
        payment.save(update_fields=["provider", "provider_notify_token"])
        with patch("core.services.subscription_payments.get_payment_provider") as provider:
            provider.return_value.fetch_transaction_status.return_value = self.verified(payment)
            result = reconcile_subscription_payment(payment)
            provider.return_value.fetch_transaction_status.assert_called_once_with(payment.external_reference)
        self.assertEqual(result.statut, "valide")

    def test_forms_do_not_offer_fake_manual_automatic_confirmation(self):
        for form in (PaiementAbonnementForm(), ManualSubscriptionPaymentForm()):
            self.assertNotIn("automatique", dict(form.fields["methode_paiement"].choices))
            self.assertIn("mobile_money", dict(form.fields["methode_paiement"].choices))

    def test_reconciliation_requires_csrf(self):
        payment = self.payment()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        with patch("core.views.reconcile_subscription_payment") as check:
            self.assertEqual(client.post(reverse("subscription_payment_check", args=[payment.pk])).status_code, 403)
            check.assert_not_called()

    def test_evidence_download_is_private_for_owner_and_super_admin_only(self):
        from tempfile import TemporaryDirectory
        from django.core.files.uploadedfile import SimpleUploadedFile
        from joatham_users.models import User
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            payment = create_subscription_payment_request(
                entreprise=self.company, plan=self.plan, duree="mensuel", reference_paiement="DEMO-PROOF",
                preuve_paiement=SimpleUploadedFile("receipt.txt", b"Fictitious proof only"),
            )
            self.client.force_login(self.owner)
            response = self.client.get(reverse("subscription_payment_evidence", args=[payment.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertIn("attachment", response["Content-Disposition"])
            self.assertEqual(b"".join(response.streaming_content), b"Fictitious proof only")
            self.assertEqual(self.client.get(reverse("subscription_payment_evidence_admin", args=[payment.pk])).status_code, 403)
            admin = User.objects.create_user(username="payment-admin", role="super_admin")
            self.client.force_login(admin)
            response = self.client.get(reverse("subscription_payment_evidence_admin", args=[payment.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"Fictitious proof only")

    def test_bilingual_statuses_history_and_confirmation_preserve_company(self):
        payment = self.payment()
        for language, heading, paid_text in (
            ("fr", "Suivi du paiement", "Votre paiement est confirmé"),
            ("en", "Payment tracking", "Your payment is confirmed"),
        ):
            self.owner.preferred_language = language
            self.owner.save(update_fields=["preferred_language"])
            self.client.force_login(self.owner)
            with self.subTest(language=language), translation.override(language):
                for status in ("en_attente", "en_cours", "annule", "expire", "echoue", "refuse", "valide"):
                    payment.statut = status
                    payment.save(update_fields=["statut"])
                    response = self.client.get(reverse("subscription_payment_detail", args=[payment.pk]))
                    self.assertContains(response, heading)
                    self.assertContains(response, self.company.nom)
                    self.assertNotContains(response, "None")
                    if status == "valide":
                        self.assertContains(response, paid_text)
                self.assertContains(self.client.get(reverse("subscription_payment_history")), payment.external_reference)
                self.assertEqual(self.client.get(reverse("subscription_payment_check", args=[payment.pk])).status_code, 405)

    def test_tenant_cannot_read_or_reconcile_another_company_payment(self):
        payment = self.payment()
        other = create_entreprise("Autre entreprise")
        intruder = create_user("other-owner", "proprietaire", other)
        self.client.force_login(intruder)
        for route in ("subscription_payment_detail", "subscription_payment_evidence"):
            self.assertEqual(self.client.get(reverse(route, args=[payment.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("subscription_payment_check", args=[payment.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("subscription_payment_history")), payment.external_reference)

    @override_settings(DEBUG=True, JOATHAM_AUTO_PAYMENT_ENABLED=True, JOATHAM_PAYMENT_PROVIDER="test")
    def test_active_same_plan_can_renew_without_immediate_activation(self):
        end = timezone.localdate() + timedelta(days=10)
        subscription = AbonnementEntreprise.objects.create(
            entreprise=self.company, plan=self.plan, statut="actif", actif=True,
            date_debut=timezone.localdate(), date_fin=end,
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse("subscription_payment_automatic_start", args=[self.plan.pk]))
        payment = PaiementAbonnement.objects.get(entreprise=self.company)
        self.assertRedirects(response, reverse("subscription_payment_detail", args=[payment.pk]))
        subscription.refresh_from_db()
        self.assertEqual(subscription.date_fin, end)


@override_settings(JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER=True)
class ConcurrentSubscriptionPaymentTests(PaymentFixtures, TransactionTestCase):
    def test_simultaneous_success_callbacks_activate_once_on_postgresql(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row locks")
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        payment = self.payment()
        verified = self.verified(payment)
        barrier = Barrier(2)
        def confirm():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return apply_verified_subscription_payment("test", verified).activated
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: confirm(), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(AbonnementEntreprise.objects.get(entreprise=self.company).date_fin, timezone.localdate() + timedelta(days=30))
