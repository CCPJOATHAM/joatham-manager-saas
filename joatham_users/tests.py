import tempfile
from io import StringIO
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Abonnement as CoreSubscription, ActivityLog, Plan
from core.selectors.subscriptions import get_subscription_with_plan_for_entreprise
from core.services.quotas import PlanQuotaExceeded
from core.services.tenancy import ensure_subscription_access_for_entreprise, get_subscription_access_state
from core.services.subscription import (
    activate_free_plan_for_entreprise,
    activate_subscription_for_entreprise,
    build_subscription_payment_estimate,
    get_current_subscription,
    get_or_create_free_plan,
    get_subscription_for_entreprise,
    has_active_subscription_access,
    is_subscription_active,
    is_subscription_expired,
    refresh_subscription_status,
    start_trial_for_entreprise,
    suspend_subscription_for_entreprise,
)
from core.services.product_policy import ACCESS_ACTIVE_ONLY, ACCESS_INCLUDED_PLAN, can_access_module, get_module_access_level
from joatham_billing.tests.factories import create_entreprise, create_user

from .models import Abonnement, AbonnementEntreprise, EntrepriseInvitation, User
from .services.invitations import (
    COMPANY_INVITATION_SOURCE_PREFIX,
    REMINDER_ERROR,
    REMINDER_SENT,
    REMINDER_SKIPPED,
    build_company_invitation_source,
    send_invitation_reminder,
)


class SubscriptionServiceTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise SaaS")
        self.autre_entreprise = create_entreprise("Entreprise SaaS B")
        self.owner = create_user("owner-saas", "proprietaire", self.entreprise)
        self.plan = Abonnement.objects.create(
            nom="Standard",
            code="standard",
            prix=29.0,
            duree_jours=30,
            actif=True,
            description="Plan standard",
        )

    def test_can_create_plan(self):
        self.assertEqual(self.plan.nom, "Standard")
        self.assertEqual(self.plan.code, "standard")
        self.assertTrue(self.plan.actif)

    def test_activate_subscription_for_entreprise(self):
        subscription = activate_subscription_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
        )

        self.entreprise.refresh_from_db()
        self.assertEqual(subscription.statut, AbonnementEntreprise.Statut.ACTIF)
        self.assertFalse(subscription.essai)
        self.assertEqual(self.entreprise.abonnement, self.plan)
        self.assertEqual(self.entreprise.date_expiration, subscription.date_fin)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="abonnement_active",
                objet_id=subscription.id,
            ).exists()
        )

    def test_start_trial_for_entreprise_rejects_new_trials(self):
        with self.assertRaisesMessage(ValueError, "creation de nouveaux essais est desactivee"):
            start_trial_for_entreprise(
                entreprise=self.entreprise,
                plan=self.plan,
                utilisateur=self.owner,
                trial_days=14,
            )

        self.assertFalse(AbonnementEntreprise.objects.filter(entreprise=self.entreprise).exists())
        self.assertFalse(ActivityLog.objects.filter(action="essai_demarre").exists())

    def test_activate_free_plan_for_entreprise(self):
        free_plan = get_or_create_free_plan()
        subscription = activate_free_plan_for_entreprise(
            entreprise=self.entreprise,
            plan=free_plan,
            utilisateur=self.owner,
        )

        self.assertEqual(subscription.statut, AbonnementEntreprise.Statut.ACTIF)
        self.assertFalse(subscription.essai)
        self.assertEqual(subscription.plan.code, "free")
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="plan_gratuit_active",
                objet_id=subscription.id,
            ).exists()
        )

    def test_expired_subscription_is_detected_and_marked(self):
        subscription = AbonnementEntreprise.objects.create(
            entreprise=self.entreprise,
            plan=self.plan,
            statut=AbonnementEntreprise.Statut.ACTIF,
            date_debut=timezone.localdate() - timedelta(days=40),
            date_fin=timezone.localdate() - timedelta(days=1),
            essai=False,
            actif=True,
        )

        self.assertTrue(is_subscription_expired(subscription))
        refresh_subscription_status(self.entreprise, utilisateur=self.owner)
        subscription.refresh_from_db()
        self.assertEqual(subscription.statut, AbonnementEntreprise.Statut.EXPIRE)
        self.assertFalse(subscription.actif)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                action="abonnement_expire",
                objet_id=subscription.id,
            ).exists()
        )

    def test_has_active_subscription_access_is_scoped_to_entreprise(self):
        activate_subscription_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
        )

        self.assertTrue(has_active_subscription_access(self.entreprise))
        self.assertFalse(has_active_subscription_access(self.autre_entreprise))

    def test_proxy_models_expose_existing_subscription_domain(self):
        self.assertEqual(Plan.objects.get(id=self.plan.id).nom, self.plan.nom)

    def test_get_subscription_for_entreprise_returns_subscription_with_plan(self):
        subscription = activate_subscription_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
        )

        selected = get_subscription_for_entreprise(self.entreprise)
        self.assertIsNotNone(selected)
        self.assertIsInstance(selected, CoreSubscription)
        self.assertEqual(selected.id, subscription.id)
        self.assertEqual(selected.plan_id, self.plan.id)

    def test_selector_returns_subscription_with_plan(self):
        subscription = activate_subscription_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
        )

        selected = get_subscription_with_plan_for_entreprise(self.entreprise)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, subscription.id)
        self.assertEqual(selected.plan.nom, self.plan.nom)

    def test_is_subscription_active_accepts_legacy_trial_by_default(self):
        AbonnementEntreprise.objects.create(
            entreprise=self.entreprise,
            plan=self.plan,
            statut=AbonnementEntreprise.Statut.ESSAI,
            date_debut=timezone.localdate(),
            date_fin=timezone.localdate() + timedelta(days=14),
            essai=True,
            actif=True,
        )

        self.assertTrue(is_subscription_active(self.entreprise))
        self.assertFalse(is_subscription_active(self.entreprise, allow_trial=False))

    def test_suspend_subscription_for_entreprise(self):
        subscription = activate_subscription_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
        )

        suspend_subscription_for_entreprise(entreprise=self.entreprise, utilisateur=self.owner)
        subscription.refresh_from_db()
        self.assertEqual(subscription.statut, AbonnementEntreprise.Statut.SUSPENDU)
        self.assertFalse(subscription.actif)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                action="abonnement_suspendu",
                objet_id=subscription.id,
            ).exists()
        )

    def test_tenancy_guard_blocks_expired_or_inactive_subscription(self):
        AbonnementEntreprise.objects.create(
            entreprise=self.entreprise,
            plan=self.plan,
            statut=AbonnementEntreprise.Statut.EXPIRE,
            date_debut=timezone.localdate() - timedelta(days=30),
            date_fin=timezone.localdate() - timedelta(days=1),
            essai=False,
            actif=False,
        )

        state = get_subscription_access_state(self.entreprise, user=self.owner)
        self.assertFalse(state["allowed"])
        self.assertIn(state["reason"], {"inactive_subscription", "expired_subscription"})

        with self.assertRaises(PermissionDenied):
            ensure_subscription_access_for_entreprise(self.entreprise, user=self.owner)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="support@joatham.local",
    JOATHAM_APP_URL="https://app.joatham.test",
)
class EntrepriseInvitationReminderTests(TestCase):
    def setUp(self):
        mail.outbox = []

    def make_invitation(self, **overrides):
        now = timezone.now()
        defaults = {
            "email": "lead@example.com",
            "full_name": "Lead Prospect",
            "created_at": now - timedelta(days=2),
            "expires_at": now + timedelta(days=5),
            "source": "question_publique",
        }
        defaults.update(overrides)
        return EntrepriseInvitation.objects.create(**defaults)

    def test_reminder_is_sent_when_conditions_are_ok(self):
        invitation = self.make_invitation()

        result = send_invitation_reminder(invitation)

        self.assertEqual(result.status, REMINDER_SENT)
        invitation.refresh_from_db()
        self.assertEqual(invitation.reminder_count, 1)
        self.assertIsNotNone(invitation.last_reminder_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["lead@example.com"])
        self.assertIn("Activer mon compte", mail.outbox[0].alternatives[0][0])
        self.assertIn("https://app.joatham.test/signup/?invitation=", mail.outbox[0].body)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise__isnull=True,
                action="invitation_relance_envoyee",
                objet_id=invitation.id,
            ).exists()
        )

    def test_no_reminder_is_sent_if_invitation_is_used(self):
        invitation = self.make_invitation(is_used=True)

        result = send_invitation_reminder(invitation)

        invitation.refresh_from_db()
        self.assertEqual(result.status, REMINDER_SKIPPED)
        self.assertEqual(result.reason, "used")
        self.assertEqual(invitation.reminder_count, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_no_reminder_is_sent_if_invitation_is_expired(self):
        invitation = self.make_invitation(expires_at=timezone.now() - timedelta(minutes=1))

        result = send_invitation_reminder(invitation)

        invitation.refresh_from_db()
        self.assertEqual(result.status, REMINDER_SKIPPED)
        self.assertEqual(result.reason, "expired")
        self.assertEqual(invitation.reminder_count, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_no_reminder_is_sent_if_max_reminders_is_reached(self):
        invitation = self.make_invitation(reminder_count=2, max_reminders=2)

        result = send_invitation_reminder(invitation)

        invitation.refresh_from_db()
        self.assertEqual(result.status, REMINDER_SKIPPED)
        self.assertEqual(result.reason, "max_reminders_reached")
        self.assertEqual(invitation.reminder_count, 2)
        self.assertEqual(len(mail.outbox), 0)

    def test_no_reminder_is_sent_if_last_reminder_is_less_than_24h(self):
        invitation = self.make_invitation(
            reminder_count=1,
            last_reminder_sent_at=timezone.now() - timedelta(hours=2),
        )

        result = send_invitation_reminder(invitation)

        invitation.refresh_from_db()
        self.assertEqual(result.status, REMINDER_SKIPPED)
        self.assertEqual(result.reason, "too_recent")
        self.assertEqual(invitation.reminder_count, 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_error_is_handled_without_incrementing_counter(self):
        invitation = self.make_invitation()

        with self.assertLogs("joatham_users.services.invitations", level="ERROR") as logs:
            with patch("joatham_users.services.invitations.EmailMultiAlternatives.send", side_effect=Exception("smtp down")):
                result = send_invitation_reminder(invitation)

        invitation.refresh_from_db()
        self.assertEqual(result.status, REMINDER_ERROR)
        self.assertEqual(result.reason, "email_error")
        self.assertEqual(invitation.reminder_count, 0)
        self.assertIsNone(invitation.last_reminder_sent_at)
        self.assertNotIn(invitation.token, "\n".join(logs.output))

    def test_management_command_sends_eligible_reminders(self):
        invitation = self.make_invitation(email="command@example.com")
        output = StringIO()

        call_command("send_invitation_reminders", stdout=output)

        invitation.refresh_from_db()
        self.assertEqual(invitation.reminder_count, 1)
        self.assertIn("total verifiees=1", output.getvalue())
        self.assertIn("envoyees=1", output.getvalue())


class SubscriptionAccessTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Access")
        self.owner = create_user("owner-access", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("gestion-access", "gestionnaire", self.entreprise)
        self.plan = Abonnement.objects.create(
            nom="Pro",
            code="pro",
            prix=49.0,
            duree_jours=30,
            actif=True,
        )

    def test_dashboard_redirects_when_subscription_is_missing(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertRedirects(response, reverse("abonnement_expire") + "?module=dashboard&reason=missing_subscription")

    def test_dashboard_allows_access_for_free_plan(self):
        activate_free_plan_for_entreprise(
            entreprise=self.entreprise,
            utilisateur=self.owner,
        )
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("gestion_dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_subscription_overview_is_owner_only(self):
        activate_subscription_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
        )

        self.client.force_login(self.gestionnaire)
        forbidden = self.client.get(reverse("subscription_overview"))
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.owner)
        allowed = self.client.get(reverse("subscription_overview"))
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "État actuel")

    def test_subscription_overview_displays_current_subscription(self):
        subscription = activate_subscription_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("subscription_overview"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["subscription"], get_current_subscription(self.entreprise))
        self.assertContains(response, subscription.plan.nom)
        self.assertContains(response, "USD")
        self.assertContains(response, "Contacter via WhatsApp")
        self.assertContains(response, "J'ai effectué le paiement")

    def test_subscription_payment_estimate_returns_local_currency_snapshot(self):
        estimate = build_subscription_payment_estimate(
            entreprise=self.entreprise,
            plan=self.plan,
            duree="mensuel",
        )

        self.assertEqual(estimate["amount_usd"], Decimal("49.00"))
        self.assertEqual(estimate["currency_code"], self.entreprise.devise)
        self.assertGreater(estimate["estimated_amount"], Decimal("0.00"))


class ProductPolicyTests(TestCase):
    def setUp(self):
        self.entreprise_legacy_trial = create_entreprise("Entreprise Legacy Trial")
        self.entreprise_active = create_entreprise("Entreprise Active")
        self.entreprise_free = create_entreprise("Entreprise Free")
        self.entreprise_none = create_entreprise("Entreprise None")
        self.owner_legacy_trial = create_user("owner-legacy-trial", "proprietaire", self.entreprise_legacy_trial)
        self.owner_active = create_user("owner-active", "proprietaire", self.entreprise_active)
        self.owner_free = create_user("owner-free", "proprietaire", self.entreprise_free)
        self.owner_none = create_user("owner-none", "proprietaire", self.entreprise_none)
        self.gestionnaire_legacy_trial = create_user("gestion-legacy-trial", "gestionnaire", self.entreprise_legacy_trial)
        self.gestionnaire_active = create_user("gestion-active", "gestionnaire", self.entreprise_active)
        self.plan = Abonnement.objects.create(
            nom="Growth",
            code="growth",
            prix=59.0,
            duree_jours=30,
            actif=True,
        )
        AbonnementEntreprise.objects.create(
            entreprise=self.entreprise_legacy_trial,
            plan=self.plan,
            statut=AbonnementEntreprise.Statut.ESSAI,
            date_debut=timezone.localdate(),
            date_fin=timezone.localdate() + timedelta(days=7),
            essai=True,
            actif=True,
        )
        activate_subscription_for_entreprise(
            entreprise=self.entreprise_active,
            plan=self.plan,
            utilisateur=self.owner_active,
        )
        activate_free_plan_for_entreprise(
            entreprise=self.entreprise_free,
            utilisateur=self.owner_free,
        )

    def test_product_policy_levels_match_current_plan_strategy(self):
        self.assertEqual(get_module_access_level("clients"), ACCESS_INCLUDED_PLAN)
        self.assertEqual(get_module_access_level("expenses"), ACCESS_INCLUDED_PLAN)
        self.assertEqual(get_module_access_level("billing"), ACCESS_INCLUDED_PLAN)
        self.assertEqual(get_module_access_level("accounting"), ACCESS_ACTIVE_ONLY)
        self.assertEqual(get_module_access_level("apprenants"), ACCESS_INCLUDED_PLAN)

    def test_free_plan_can_access_only_included_modules(self):
        self.assertTrue(can_access_module(self.owner_free, "clients"))
        self.assertTrue(can_access_module(self.owner_free, "expenses"))
        self.assertTrue(can_access_module(self.owner_free, "billing"))
        self.assertFalse(can_access_module(self.owner_free, "apprenants"))
        self.assertFalse(can_access_module(self.owner_free, "accounting"))

    def test_legacy_trial_keeps_compatible_access(self):
        self.assertTrue(can_access_module(self.owner_legacy_trial, "clients"))
        self.assertTrue(can_access_module(self.owner_legacy_trial, "expenses"))
        self.assertTrue(can_access_module(self.owner_legacy_trial, "billing"))
        self.assertTrue(can_access_module(self.owner_legacy_trial, "apprenants"))
        self.assertFalse(can_access_module(self.owner_legacy_trial, "accounting"))

    def test_active_can_access_all_targeted_modules(self):
        self.assertTrue(can_access_module(self.owner_active, "clients"))
        self.assertTrue(can_access_module(self.owner_active, "expenses"))
        self.assertTrue(can_access_module(self.owner_active, "billing"))
        self.assertTrue(can_access_module(self.owner_active, "accounting"))
        self.assertTrue(can_access_module(self.owner_active, "apprenants"))

    def test_missing_subscription_blocks_protected_modules(self):
        self.assertFalse(can_access_module(self.owner_none, "clients"))
        self.assertFalse(can_access_module(self.owner_none, "billing"))

    def test_clients_view_is_allowed_with_free_plan(self):
        self.client.force_login(self.owner_free)
        response = self.client.get(reverse("client_list"))
        self.assertEqual(response.status_code, 200)

    def test_depenses_view_is_allowed_with_free_plan(self):
        self.client.force_login(self.owner_free)
        response = self.client.get(reverse("depenses"))
        self.assertEqual(response.status_code, 200)

    def test_billing_view_is_allowed_with_free_plan(self):
        self.client.force_login(self.owner_free)
        response = self.client.get(reverse("facture_list"))
        self.assertEqual(response.status_code, 200)

    def test_accounting_view_is_refused_with_free_plan(self):
        self.client.force_login(self.owner_free)
        response = self.client.get(reverse("compta_dashboard"))
        self.assertRedirects(response, reverse("abonnement_expire") + "?module=accounting&reason=premium_required")

    def test_accounting_view_is_allowed_when_active(self):
        comptable_active = create_user("compta-active", "comptable", self.entreprise_active)
        self.client.force_login(comptable_active)
        response = self.client.get(reverse("compta_dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_apprenants_view_is_allowed_for_legacy_trial(self):
        self.client.force_login(self.gestionnaire_legacy_trial)
        response = self.client.get(reverse("apprenant_list"))
        self.assertEqual(response.status_code, 200)

    def test_free_plan_locks_premium_modules(self):
        self.assertFalse(can_access_module(self.owner_free, "inventory"))
        self.assertFalse(can_access_module(self.owner_free, "stock_reports"))
        self.assertFalse(can_access_module(self.owner_free, "stock_exports"))
        self.assertFalse(can_access_module(self.owner_free, "accounting"))
        self.assertFalse(can_access_module(self.owner_free, "audit"))
        self.assertFalse(can_access_module(self.owner_free, "messages"))
        self.assertFalse(can_access_module(self.owner_free, "users"))

    def test_expired_or_suspended_subscription_blocks_targeted_views(self):
        suspend_subscription_for_entreprise(entreprise=self.entreprise_active, utilisateur=self.owner_active)
        self.client.force_login(self.gestionnaire_active)
        response = self.client.get(reverse("client_list"))
        self.assertRedirects(response, reverse("abonnement_expire") + "?module=clients&reason=inactive_subscription")

    def test_subscription_isolation_is_kept_per_entreprise(self):
        self.client.force_login(self.owner_none)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertRedirects(response, reverse("abonnement_expire") + "?module=dashboard&reason=missing_subscription")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="support@joatham.local",
    JOATHAM_APP_URL="https://app.joatham.test",
)
class UserManagementTests(TestCase):
    def setUp(self):
        mail.outbox = []
        self.entreprise = create_entreprise("Entreprise Utilisateurs")
        self.autre_entreprise = create_entreprise("Entreprise Externe")
        self.entreprise_free = create_entreprise("Entreprise Freemium")
        self.owner = create_user("owner-users", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("gestion-users", "gestionnaire", self.entreprise)
        self.comptable = create_user("compta-users", "comptable", self.entreprise)
        self.external_user = create_user("external-users", "gestionnaire", self.autre_entreprise)
        self.owner_free = create_user("owner-free-users", "proprietaire", self.entreprise_free)
        self.plan = Abonnement.objects.create(
            nom="Users",
            code="users",
            prix=15.0,
            duree_jours=30,
            actif=True,
            max_utilisateurs=10,
        )
        activate_subscription_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
        )
        activate_subscription_for_entreprise(
            entreprise=self.autre_entreprise,
            plan=self.plan,
            utilisateur=self.external_user,
        )
        activate_free_plan_for_entreprise(
            entreprise=self.entreprise_free,
            utilisateur=self.owner_free,
        )

    def test_owner_can_access_user_list(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("user_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestion des utilisateurs")
        self.assertContains(response, "Utilisateurs total")
        self.assertContains(response, "Ajouter un utilisateur")
        self.assertContains(response, reverse("user_create"))

    def test_user_list_displays_role_and_status_badges(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("user_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Compte proprietaire principal")
        self.assertContains(response, "Gestionnaire")
        self.assertContains(response, "Comptable")
        self.assertContains(response, "Actif")
        self.assertContains(response, "Invitations en attente")
        self.assertContains(response, "Quota utilise")

    def test_user_list_is_limited_to_current_company(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("user_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.gestionnaire.username)
        self.assertNotContains(response, self.external_user.username)

    def test_owner_can_filter_user_list(self):
        self.gestionnaire.email = "gestion.filtre@example.com"
        self.gestionnaire.save(update_fields=["email"])

        self.client.force_login(self.owner)
        response = self.client.get(reverse("user_list"), {"role": User.Role.COMPTABLE})
        self.assertContains(response, self.comptable.username)
        self.assertNotContains(response, self.gestionnaire.username)

        response = self.client.get(reverse("user_list"), {"q": "gestion.filtre"})
        self.assertContains(response, "gestion.filtre@example.com")
        self.assertNotContains(response, self.comptable.username)

    def test_non_owner_cannot_access_user_management(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("user_list"))
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.comptable)
        response = self.client.get(reverse("user_list"))
        self.assertEqual(response.status_code, 403)

    def test_owner_can_create_company_user(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("user_create"),
            {
                "full_name": "Marie Gestion",
                "email": "marie.gestion@example.com",
                "telephone": "+243900000099",
                "role": User.Role.GESTIONNAIRE,
                "password": "Motdepasse123!",
            },
        )
        self.assertRedirects(response, reverse("user_list"))
        created_user = User.objects.get(email="marie.gestion@example.com")
        self.assertEqual(created_user.entreprise, self.entreprise)
        self.assertEqual(created_user.role, User.Role.GESTIONNAIRE)
        self.assertEqual(created_user.telephone, "+243900000099")

    def test_owner_can_invite_gestionnaire(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("user_invite"),
            {
                "full_name": "Marie Invitee",
                "email": "marie.invitee@example.com",
                "role": User.Role.GESTIONNAIRE,
            },
        )

        self.assertRedirects(response, reverse("user_list"))
        invitation = EntrepriseInvitation.objects.get(email="marie.invitee@example.com")
        self.assertEqual(invitation.source, build_company_invitation_source(self.entreprise, User.Role.GESTIONNAIRE))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/utilisateurs/invitations/", mail.outbox[0].body)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="utilisateur_invite",
                objet_id=invitation.id,
            ).exists()
        )

    def test_owner_can_invite_comptable(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("user_invite"),
            {
                "full_name": "Claude Comptable",
                "email": "claude.comptable@example.com",
                "role": User.Role.COMPTABLE,
            },
        )

        self.assertRedirects(response, reverse("user_list"))
        invitation = EntrepriseInvitation.objects.get(email="claude.comptable@example.com")
        self.assertIn(f"{COMPANY_INVITATION_SOURCE_PREFIX}:{self.entreprise.id}:{User.Role.COMPTABLE}", invitation.source)

    def test_invitation_is_blocked_when_quota_is_exceeded(self):
        quota_entreprise = create_entreprise("Entreprise Quota Users")
        quota_owner = create_user("owner-quota-users", User.Role.PROPRIETAIRE, quota_entreprise)
        quota_plan = Abonnement.objects.create(
            nom="Quota",
            code="quota",
            prix=10.0,
            duree_jours=30,
            actif=True,
            max_utilisateurs=1,
        )
        activate_subscription_for_entreprise(
            entreprise=quota_entreprise,
            plan=quota_plan,
            utilisateur=quota_owner,
        )

        self.client.force_login(quota_owner)
        response = self.client.post(
            reverse("user_invite"),
            {
                "full_name": "Invite Bloque",
                "email": "invite.bloque@example.com",
                "role": User.Role.GESTIONNAIRE,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cette fonctionnalite n&#x27;est pas incluse dans votre plan actuel")
        self.assertContains(response, "Votre plan permet jusqu&#x27;a 1 utilisateur(s), invitations en attente incluses.")
        self.assertFalse(EntrepriseInvitation.objects.filter(email="invite.bloque@example.com").exists())

    def test_invitation_is_blocked_when_email_is_already_used(self):
        self.gestionnaire.email = "gestionnaire.used@example.com"
        self.gestionnaire.save(update_fields=["email"])

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("user_invite"),
            {
                "full_name": "Doublon",
                "email": "gestionnaire.used@example.com",
                "role": User.Role.GESTIONNAIRE,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Un utilisateur de cette entreprise utilise deja cet email")
        self.assertFalse(EntrepriseInvitation.objects.filter(email="gestionnaire.used@example.com").exists())

    def test_invitation_is_blocked_when_active_duplicate_exists(self):
        EntrepriseInvitation.objects.create(
            email="duplicate.invite@example.com",
            full_name="Duplicate Invite",
            source=build_company_invitation_source(self.entreprise, User.Role.COMPTABLE),
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("user_invite"),
            {
                "full_name": "Duplicate Invite",
                "email": "duplicate.invite@example.com",
                "role": User.Role.COMPTABLE,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Une invitation active existe deja pour cet email")
        self.assertEqual(EntrepriseInvitation.objects.filter(email="duplicate.invite@example.com").count(), 1)

    def test_owner_can_resend_and_cancel_invitation(self):
        invitation = EntrepriseInvitation.objects.create(
            email="resend.invite@example.com",
            full_name="Resend Invite",
            source=build_company_invitation_source(self.entreprise, User.Role.GESTIONNAIRE),
        )

        self.client.force_login(self.owner)
        response = self.client.post(reverse("user_invitation_resend", args=[invitation.id]))
        self.assertRedirects(response, reverse("user_list"))
        invitation.refresh_from_db()
        self.assertEqual(invitation.reminder_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(ActivityLog.objects.filter(action="invitation_renvoyee", objet_id=invitation.id).exists())

        response = self.client.post(reverse("user_invitation_cancel", args=[invitation.id]))
        self.assertRedirects(response, reverse("user_list"))
        invitation.refresh_from_db()
        self.assertTrue(invitation.is_used)
        self.assertTrue(ActivityLog.objects.filter(action="invitation_annulee", objet_id=invitation.id).exists())

    def test_invited_user_can_accept_company_invitation(self):
        invitation = EntrepriseInvitation.objects.create(
            email="accept.invite@example.com",
            full_name="Accept Invite",
            source=build_company_invitation_source(self.entreprise, User.Role.GESTIONNAIRE),
        )

        response = self.client.get(reverse("user_invitation_accept", args=[invitation.token]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "accept.invite@example.com")

        response = self.client.post(
            reverse("user_invitation_accept", args=[invitation.token]),
            {
                "password": "Motdepasse123!",
                "password_confirm": "Motdepasse123!",
            },
        )
        self.assertRedirects(response, reverse("gestion_dashboard"))
        invitation.refresh_from_db()
        accepted_user = User.objects.get(email="accept.invite@example.com")
        self.assertEqual(accepted_user.entreprise, self.entreprise)
        self.assertEqual(accepted_user.role, User.Role.GESTIONNAIRE)
        self.assertTrue(invitation.is_used)
        self.assertTrue(ActivityLog.objects.filter(action="invitation_acceptee", objet_id=invitation.id).exists())

    def test_free_plan_blocks_company_user_creation(self):
        self.client.force_login(self.owner_free)
        response = self.client.post(
            reverse("user_create"),
            {
                "full_name": "Marie Gestion",
                "email": "blocked.freemium@example.com",
                "telephone": "+243900000188",
                "role": User.Role.GESTIONNAIRE,
                "password": "Motdepasse123!",
            },
        )

        self.assertRedirects(response, reverse("abonnement_expire") + "?module=users&reason=module_not_in_plan")
        self.assertFalse(User.objects.filter(email="blocked.freemium@example.com").exists())

    def test_user_form_renders_premium_layout(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("user_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Repere rapide")
        self.assertContains(response, "Nom complet")
        self.assertContains(response, "Roles geres : Gestionnaire / Comptable")

    def test_owner_can_update_company_user(self):
        managed_user = User.objects.create_user(
            username="user-update@example.com",
            email="user-update@example.com",
            password="Initial123!",
            role=User.Role.COMPTABLE,
            entreprise=self.entreprise,
            telephone="+243111",
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("user_update", args=[managed_user.id]),
            {
                "full_name": "Paul Comptable",
                "email": "paul.comptable@example.com",
                "telephone": "+243222",
                "role": User.Role.GESTIONNAIRE,
                "password": "",
            },
        )
        self.assertRedirects(response, reverse("user_list"))
        managed_user.refresh_from_db()
        self.assertEqual(managed_user.email, "paul.comptable@example.com")
        self.assertEqual(managed_user.role, User.Role.GESTIONNAIRE)
        self.assertEqual(managed_user.telephone, "+243222")

    def test_non_owner_cannot_change_company_user_role(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("user_update", args=[self.comptable.id]),
            {
                "full_name": "Comptable Bloque",
                "email": "blocked.role@example.com",
                "telephone": "",
                "role": User.Role.GESTIONNAIRE,
                "password": "",
            },
        )
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.comptable)
        response = self.client.post(
            reverse("user_update", args=[self.gestionnaire.id]),
            {
                "full_name": "Gestionnaire Bloque",
                "email": "blocked.role.2@example.com",
                "telephone": "",
                "role": User.Role.COMPTABLE,
                "password": "",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_owner_can_toggle_user_status(self):
        managed_user = User.objects.create_user(
            username="toggle@example.com",
            email="toggle@example.com",
            password="Initial123!",
            role=User.Role.COMPTABLE,
            entreprise=self.entreprise,
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse("user_toggle_active", args=[managed_user.id]))
        self.assertRedirects(response, reverse("user_list"))
        managed_user.refresh_from_db()
        self.assertFalse(managed_user.is_active)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                action="utilisateur_statut_modifie",
                objet_id=managed_user.id,
            ).exists()
        )

    def test_owner_cannot_deactivate_owner_account_from_company_management(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("user_toggle_active", args=[self.owner.id]))
        self.assertRedirects(response, reverse("user_list"))
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)

    def test_owner_can_remove_secondary_user_access(self):
        managed_user = User.objects.create_user(
            username="remove-access@example.com",
            email="remove-access@example.com",
            password="Initial123!",
            role=User.Role.COMPTABLE,
            entreprise=self.entreprise,
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse("user_remove_access", args=[managed_user.id]))
        self.assertRedirects(response, reverse("user_list"))
        managed_user.refresh_from_db()
        self.assertFalse(managed_user.is_active)
        self.assertTrue(ActivityLog.objects.filter(action="utilisateur_acces_retire", objet_id=managed_user.id).exists())

    def test_owner_can_delete_secondary_user(self):
        managed_user = User.objects.create_user(
            username="delete@example.com",
            email="delete@example.com",
            password="Initial123!",
            role=User.Role.GESTIONNAIRE,
            entreprise=self.entreprise,
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse("user_delete", args=[managed_user.id]))
        self.assertRedirects(response, reverse("user_list"))
        self.assertFalse(User.objects.filter(id=managed_user.id).exists())

    def test_multi_entreprise_isolation_prevents_cross_company_access(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("user_update", args=[self.external_user.id]))
        self.assertEqual(response.status_code, 404)

        response = self.client.get(reverse("user_detail", args=[self.external_user.id]))
        self.assertEqual(response.status_code, 404)

    def test_owner_can_update_company_settings_with_tva_and_referentiel(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("company_settings"),
            {
                "nom": "Entreprise Utilisateurs",
                "raison_sociale": "Entreprise Utilisateurs SARL",
                "adresse": "Avenue Test 1",
                "ville": "Kinshasa",
                "pays": "CD",
                "devise": "CDF",
                "taux_tva_defaut": "18.50",
                "referentiel_comptable": "pcg",
                "telephone": "+243000111222",
                "email": "contact@example.com",
                "banque": "Banque Test",
                "compte_bancaire": "123456",
                "rccm": "RCCM-1",
                "id_nat": "IDNAT-1",
                "numero_impot": "IMPOT-1",
            },
        )

        self.assertRedirects(response, reverse("company_settings"))
        self.entreprise.refresh_from_db()
        self.assertEqual(self.entreprise.taux_tva_defaut, Decimal("18.50"))
        self.assertEqual(self.entreprise.referentiel_comptable, "pcg")


class ProfileTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_root.cleanup)

        self.entreprise = create_entreprise("Entreprise Profil")
        self.autre_entreprise = create_entreprise("Entreprise Autre")
        self.user = create_user("profil-user", User.Role.GESTIONNAIRE, self.entreprise)
        self.user.first_name = "Jean"
        self.user.last_name = "Profil"
        self.user.email = "jean.profil@example.com"
        self.user.telephone = "+243810000000"
        self.user.preferred_language = "fr"
        self.user.save()
        self.other_user = create_user("autre-profil", User.Role.COMPTABLE, self.autre_entreprise)

    def test_profile_requires_authenticated_user(self):
        response = self.client.get(reverse("profile"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_user_sees_profile_information(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mon profil")
        self.assertContains(response, "profil-user")
        self.assertContains(response, "Jean Profil")
        self.assertContains(response, "jean.profil@example.com")
        self.assertContains(response, "+243810000000")
        self.assertContains(response, "Gestionnaire")
        self.assertContains(response, "Entreprise Profil")
        self.assertContains(response, "Fran")

    def test_user_can_update_allowed_profile_fields(self):
        avatar = SimpleUploadedFile(
            "avatar.gif",
            b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("profile"),
            {
                "full_name": "Jeanne Profil",
                "telephone": "+243820000000",
                "preferred_language": "en",
                "profile_photo": avatar,
            },
        )

        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Jeanne")
        self.assertEqual(self.user.last_name, "Profil")
        self.assertEqual(self.user.telephone, "+243820000000")
        self.assertEqual(self.user.preferred_language, "en")
        self.assertTrue(self.user.profile_photo.name.startswith("profiles/avatar"))

    def test_user_cannot_update_sensitive_profile_fields(self):
        original_email = self.user.email
        original_role = self.user.role
        original_entreprise = self.user.entreprise

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("profile"),
            {
                "id": self.other_user.id,
                "full_name": "Jean Modifie",
                "telephone": "+243830000000",
                "preferred_language": "pt",
                "email": "attacker@example.com",
                "role": User.Role.PROPRIETAIRE,
                "entreprise": self.autre_entreprise.id,
            },
        )

        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.other_user.refresh_from_db()
        self.assertEqual(self.user.email, original_email)
        self.assertEqual(self.user.role, original_role)
        self.assertEqual(self.user.entreprise, original_entreprise)
        self.assertEqual(self.user.telephone, "+243830000000")
        self.assertEqual(self.user.preferred_language, "pt")
        self.assertNotEqual(self.other_user.telephone, "+243830000000")
