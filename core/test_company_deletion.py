"""All destructive-intent scenarios run on isolated test data; purge stays blocked."""
from datetime import timedelta
from io import StringIO
import json
from unittest.mock import patch

from django.contrib import admin
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.core.management import call_command, CommandError
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from core.models import ActivityLog, CompanyDeletionRequest, PaiementAbonnement
from core.services.company_deletion import (
    DeletionWorkflowError, build_purge_plan, cancel_deletion, export_company,
    purge_company, schedule_deletion,
)
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_billing.tests.factories import create_entreprise, create_user, create_client, create_facture_sample
from joatham_users.models import Abonnement, AbonnementEntreprise, Entreprise, User, UserActiveSession


class CompanyDeletionTests(TestCase):
    def setUp(self):
        self.company = create_entreprise("Société Àvenir")
        self.other = create_entreprise("Entreprise étrangère confidentielle")
        self.owner = create_user("deletion-owner", "proprietaire", self.company)
        self.disabled = create_user("disabled-person", "gestionnaire", self.company)
        self.disabled.is_active = False
        self.disabled.save(update_fields=["is_active"])
        self.super_admin = User.objects.create_user(username="deletion-admin", role="super_admin", password="testpass123")
        self.plan = Abonnement.objects.create(nom="Starter", code="starter", prix=10, duree_jours=30, actif=True)
        self.subscription = AbonnementEntreprise.objects.create(
            entreprise=self.company, plan=self.plan, date_debut=timezone.localdate(),
            date_fin=timezone.localdate() + timedelta(days=20), statut="actif", actif=True,
        )
        self.url = reverse("super_admin_company_deletion", args=[self.company.pk])
        self.args = dict(company_id=self.company.pk, actor=self.super_admin,
                         confirmation_name=self.company.nom, reason="Demande motivée — texte inchangé")

    def test_only_active_super_admin_can_access_or_schedule(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        for role in ("proprietaire", "gestionnaire", "comptable"):
            actor = create_user("forbidden-" + role, role, self.other)
            self.client.force_login(actor)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url, {"action": "schedule", "confirmation_name": self.company.nom, "reason": "test"}).status_code, 403)
            with self.assertRaises(PermissionDenied):
                schedule_deletion(**{**self.args, "actor": actor})
        self.super_admin.is_active = False
        self.super_admin.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            schedule_deletion(**self.args)
        self.assertFalse(CompanyDeletionRequest.objects.exists())

    def test_post_requires_csrf_and_get_is_read_only(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.super_admin)
        self.assertEqual(client.get(self.url).status_code, 200)
        self.assertEqual(client.post(self.url, {"action": "schedule", "confirmation_name": self.company.nom, "reason": "test"}).status_code, 403)
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_active)
        self.assertFalse(CompanyDeletionRequest.objects.exists())

    def test_exact_name_and_nonempty_reason_are_required(self):
        for name, reason in (("wrong", "test"), (self.company.nom + " ", "test"), (self.company.nom.lower(), "test"), (self.company.nom, "  ")):
            with self.assertRaises(DeletionWorkflowError):
                schedule_deletion(**{**self.args, "confirmation_name": name, "reason": reason})
        self.assertFalse(CompanyDeletionRequest.objects.exists())
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_active)

    def test_schedule_revokes_sessions_but_preserves_accounts_business_and_subscription(self):
        invoice = create_facture_sample(self.company, self.owner)
        session = Session.objects.create(session_key="tenant-session", session_data="fictitious", expire_date=timezone.now() + timedelta(days=1))
        UserActiveSession.objects.create(user=self.owner, session_key=session.session_key)
        other_session = Session.objects.create(session_key="unrelated-session", session_data="fictitious", expire_date=timezone.now() + timedelta(days=1))
        before = timezone.now()
        request = schedule_deletion(**self.args)
        self.company.refresh_from_db(); self.owner.refresh_from_db(); self.disabled.refresh_from_db(); self.subscription.refresh_from_db()
        self.assertFalse(self.company.is_active)
        self.assertTrue(self.owner.is_active)
        self.assertFalse(self.disabled.is_active)
        self.assertFalse(Session.objects.filter(pk=session.pk).exists())
        self.assertTrue(Session.objects.filter(pk=other_session.pk).exists())
        self.assertTrue(type(invoice).objects.filter(pk=invoice.pk).exists())
        self.assertEqual(self.subscription.date_fin, timezone.localdate() + timedelta(days=20))
        self.assertTrue(self.subscription.actif)
        self.assertEqual(request.recovery_until - request.requested_at, timedelta(days=30))
        self.assertGreaterEqual(request.requested_at, before)
        event = ActivityLog.objects.get(action="company_deletion_scheduled")
        self.assertEqual(event.utilisateur, self.super_admin)
        self.assertEqual(event.metadata["reason"], self.args["reason"])

    @override_settings(JOATHAM_COMPANY_DELETION_GRACE_DAYS=45)
    def test_delay_is_snapshotted_and_duplicate_does_not_reset_it(self):
        request = schedule_deletion(**self.args)
        deadline = request.recovery_until
        self.assertEqual(deadline - request.requested_at, timedelta(days=45))
        with override_settings(JOATHAM_COMPANY_DELETION_GRACE_DAYS=1), self.assertRaises(DeletionWorkflowError):
            schedule_deletion(**self.args)
        request.refresh_from_db()
        self.assertEqual(request.recovery_until, deadline)

    def test_audit_failure_rolls_back_schedule(self):
        with patch("core.services.company_deletion.record_audit_event", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                schedule_deletion(**self.args)
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_active)
        self.assertFalse(CompanyDeletionRequest.objects.exists())

    def test_pending_request_blocks_session_login_and_reactivation_bypass(self):
        schedule_deletion(**self.args)
        # A different legacy screen accidentally sets is_active back to True.
        Entreprise.objects.filter(pk=self.company.pk).update(is_active=True)
        self.company.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            get_user_entreprise_or_raise(self.owner)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)
        login = self.client.post(reverse("login"), {"username": self.owner.username, "password": "testpass123"})
        self.assertContains(login, "demande de suppression")
        self.assertNotIn("_auth_user_id", self.client.session)
        from rest_framework.test import APIClient
        api = APIClient()
        api.force_authenticate(self.owner)
        self.assertEqual(api.get("/api/clients/").status_code, 403)

    def test_cancel_restores_previous_activation_flags_and_never_extends_subscription(self):
        schedule_deletion(**self.args)
        cancel_deletion(**self.args)
        self.company.refresh_from_db(); self.disabled.refresh_from_db(); self.subscription.refresh_from_db()
        self.assertTrue(self.company.is_active)
        self.assertFalse(self.disabled.is_active)
        self.assertEqual(self.subscription.date_fin, timezone.localdate() + timedelta(days=20))
        self.assertEqual(CompanyDeletionRequest.objects.get(entreprise=self.company).status, "cancelled")
        with self.assertRaises(DeletionWorkflowError):
            cancel_deletion(**self.args)
        self.assertEqual(ActivityLog.objects.filter(action="company_deletion_cancelled").count(), 1)

    def test_cancel_does_not_reactivate_previously_inactive_company(self):
        self.company.is_active = False
        self.company.save(update_fields=["is_active"])
        schedule_deletion(**self.args)
        cancel_deletion(**self.args)
        self.company.refresh_from_db()
        self.assertFalse(self.company.is_active)

    def test_after_thirty_days_retention_hold_and_restore_remain_available(self):
        request = schedule_deletion(**self.args)
        with patch("core.services.company_deletion.timezone.now", return_value=request.recovery_until):
            plan, _ = build_purge_plan(self.company)
            self.assertTrue(plan["recovery_window_expired"])
            self.assertFalse(plan["purge_permitted"])
            cancel_deletion(**self.args)
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_active)

    def test_reschedule_after_cancellation_creates_a_fresh_recovery_window(self):
        first = schedule_deletion(**self.args)
        cancel_deletion(**self.args)
        with patch("core.services.company_deletion.timezone.now", return_value=first.requested_at + timedelta(days=3)):
            second = schedule_deletion(**self.args)
        self.assertEqual(second.requested_at, first.requested_at + timedelta(days=3))
        self.assertEqual(ActivityLog.objects.filter(action="company_deletion_scheduled").count(), 2)

    def test_export_is_tenant_scoped_and_excludes_credentials(self):
        other_client = create_client(self.other, "SECRET FOREIGN CLIENT")
        foreign_invoice = create_facture_sample(self.other, create_user("foreign-owner", "proprietaire", self.other), other_client)
        own_invoice = create_facture_sample(self.company, self.owner)
        payment = PaiementAbonnement.objects.create(
            entreprise=self.company, plan=self.plan, duree="mensuel", montant=10,
            provider_notify_token="HIDDEN-NOTIFY", provider_checkout_id="HIDDEN-CHECKOUT",
            raw_provider_payload={"password": "HIDDEN-RAW"},
        )
        content = export_company(**self.args).decode()
        for forbidden in (self.other.nom, "SECRET FOREIGN CLIENT", self.owner.password, "HIDDEN-NOTIFY", "HIDDEN-CHECKOUT", "HIDDEN-RAW"):
            self.assertNotIn(forbidden, content)
        payload = json.loads(content)
        self.assertFalse(payload["binary_files_included"])
        self.assertEqual(payload["company_id"], self.company.pk)
        self.assertTrue(any(row["id"] == own_invoice.pk for row in payload["data"]["joatham_billing.facture"]))
        self.assertEqual(len(payload["data"]["joatham_billing.facture"]), 1)
        self.assertNotIn("password", payload["data"]["joatham_users.user"][0])
        self.assertFalse(CompanyDeletionRequest.objects.exists())
        self.assertTrue(type(foreign_invoice).objects.filter(pk=foreign_invoice.pk).exists())
        self.assertTrue(PaiementAbonnement.objects.filter(pk=payment.pk).exists())

    def test_inconsistent_cross_company_link_blocks_export_instead_of_leaking(self):
        foreign_client = create_client(self.other, "FOREIGN PRIVATE DATA")
        invoice = create_facture_sample(self.company, self.owner)
        invoice.client = foreign_client
        invoice.save(update_fields=["client"])
        with self.assertRaises(DeletionWorkflowError):
            export_company(**self.args)
        self.assertTrue(type(invoice).objects.filter(pk=invoice.pk).exists())
        self.assertFalse(ActivityLog.objects.filter(action="company_deletion_exported").exists())

    def test_export_http_is_attachment_private_and_does_not_schedule(self):
        self.client.force_login(self.super_admin)
        response = self.client.post(self.url, {"action": "export", "confirmation_name": self.company.nom, "reason": "Avant fermeture"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertFalse(CompanyDeletionRequest.objects.exists())

    @override_settings(JOATHAM_COMPANY_EXPORT_MAX_ROWS=1)
    def test_export_volume_limit_fails_closed(self):
        with self.assertRaises(DeletionWorkflowError):
            export_company(**self.args)

    def test_simulation_is_read_only_and_reveals_retention_blockers(self):
        invoice = create_facture_sample(self.company, self.owner)
        request = schedule_deletion(**self.args)
        before_logs = ActivityLog.objects.count()
        out = StringIO()
        call_command("purger_entreprise", str(self.company.pk), actor_id=self.super_admin.pk, simulate=True, stdout=out)
        plan = json.loads(out.getvalue())
        self.assertEqual(plan["mode"], "simulation_only")
        self.assertFalse(plan["purge_permitted"])
        self.assertIn("joatham_billing.facture", plan["retention_blockers"])
        self.assertEqual(ActivityLog.objects.count(), before_logs)
        self.assertTrue(type(invoice).objects.filter(pk=invoice.pk).exists())
        request.refresh_from_db()
        self.assertEqual(request.status, "pending")

    def test_real_purge_cannot_be_unlocked_even_with_all_confirmations(self):
        request = schedule_deletion(**self.args)
        with patch("core.services.company_deletion.timezone.now", return_value=request.recovery_until + timedelta(days=365)), override_settings(JOATHAM_COMPANY_PURGE_ENABLED=True):
            plan, _ = build_purge_plan(self.company)
            with self.assertRaises(DeletionWorkflowError):
                purge_company(**self.args, plan_hash=plan["plan_hash"], retention_review="operator supplied approval")
            with self.assertRaises(CommandError):
                call_command("purger_entreprise", str(self.company.pk), actor_id=self.super_admin.pk, execute=True,
                             confirmation_name=self.company.nom, reason="Explicit intent", plan_hash=plan["plan_hash"], retention_review="approval")
        self.assertTrue(Entreprise.objects.filter(pk=self.company.pk).exists())
        self.assertEqual(ActivityLog.objects.filter(action="company_deletion_purge_blocked").count(), 2)

    def test_admin_and_protected_relations_prevent_direct_company_audit_deletion(self):
        schedule_deletion(**self.args)
        self.assertFalse(admin.site._registry[Entreprise].has_delete_permission(None, self.company))
        self.assertFalse(admin.site._registry[ActivityLog].has_delete_permission(None))
        with self.assertRaises(ProtectedError):
            self.company.delete()
        self.assertTrue(ActivityLog.objects.filter(entreprise=self.company).exists())

    def test_privileged_platform_account_prevents_scheduling(self):
        self.super_admin.entreprise = self.company
        self.super_admin.save(update_fields=["entreprise"])
        with self.assertRaises(DeletionWorkflowError):
            schedule_deletion(**self.args)

    def test_french_and_english_ui_and_audit_leave_free_text_intact(self):
        schedule_deletion(**self.args)
        for language, title, action in (("fr", "Entreprise concernée", "Suppression programmée"), ("en", "Company concerned", "Deletion scheduled")):
            self.super_admin.preferred_language = language
            self.super_admin.save(update_fields=["preferred_language"])
            self.client.force_login(self.super_admin)
            with self.subTest(language=language), translation.override(language):
                response = self.client.get(self.url)
                self.assertContains(response, title)
                self.assertContains(response, self.company.nom)
                self.assertNotContains(response, self.other.nom)
                event = ActivityLog.objects.get(action="company_deletion_scheduled")
                self.assertEqual(event.display_action, action)
                self.assertEqual(event.metadata["reason"], self.args["reason"])
                self.assertNotEqual(event.display_description, event.description)

class CompanyDeletionConcurrencyTests(TransactionTestCase):
    def test_simultaneous_scheduling_does_not_reset_window_or_duplicate_audit(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connection, connections
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL row locks required")
        company = create_entreprise("Concurrent fictitious tenant")
        actor = User.objects.create_user(username="concurrent-admin", role="super_admin")
        barrier = Barrier(2)
        def schedule():
            try:
                barrier.wait(timeout=10)
                try:
                    return schedule_deletion(company_id=company.pk, actor=actor, confirmation_name=company.nom, reason="Concurrent test").pk
                except DeletionWorkflowError:
                    return None
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(schedule) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(CompanyDeletionRequest.objects.filter(entreprise=company).count(), 1)
        self.assertEqual(ActivityLog.objects.filter(action="company_deletion_scheduled").count(), 1)
