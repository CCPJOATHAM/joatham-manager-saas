from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Abonnement as CoreSubscription, ActivityLog, Plan
from core.selectors.subscriptions import get_subscription_with_plan_for_entreprise
from core.services.tenancy import ensure_subscription_access_for_entreprise, get_subscription_access_state
from core.services.subscription import (
    activate_subscription_for_entreprise,
    build_subscription_payment_estimate,
    get_current_subscription,
    get_subscription_for_entreprise,
    has_active_subscription_access,
    is_subscription_active,
    is_subscription_expired,
    refresh_subscription_status,
    start_trial_for_entreprise,
    suspend_subscription_for_entreprise,
)
from core.services.product_policy import ACCESS_ACTIVE_ONLY, ACCESS_TRIAL_OR_ACTIVE, can_access_module, get_module_access_level
from joatham_billing.tests.factories import create_entreprise, create_user

from .models import Abonnement, AbonnementEntreprise, User


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

    def test_start_trial_for_entreprise(self):
        subscription = start_trial_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
            trial_days=14,
        )

        self.assertEqual(subscription.statut, AbonnementEntreprise.Statut.ESSAI)
        self.assertTrue(subscription.essai)
        self.assertEqual(subscription.date_fin, timezone.localdate() + timedelta(days=14))
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="essai_demarre",
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
        subscription = start_trial_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
            trial_days=14,
        )

        selected = get_subscription_with_plan_for_entreprise(self.entreprise)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, subscription.id)
        self.assertEqual(selected.plan.nom, self.plan.nom)

    def test_is_subscription_active_accepts_trial_by_default(self):
        start_trial_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
            trial_days=14,
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

    def test_dashboard_allows_access_for_trial_subscription(self):
        start_trial_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
            trial_days=7,
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
        self.entreprise_trial = create_entreprise("Entreprise Trial")
        self.entreprise_active = create_entreprise("Entreprise Active")
        self.entreprise_none = create_entreprise("Entreprise None")
        self.owner_trial = create_user("owner-trial", "proprietaire", self.entreprise_trial)
        self.owner_active = create_user("owner-active", "proprietaire", self.entreprise_active)
        self.owner_none = create_user("owner-none", "proprietaire", self.entreprise_none)
        self.gestionnaire_trial = create_user("gestion-trial", "gestionnaire", self.entreprise_trial)
        self.gestionnaire_active = create_user("gestion-active", "gestionnaire", self.entreprise_active)
        self.comptable_trial = create_user("compta-trial", "comptable", self.entreprise_trial)
        self.plan = Abonnement.objects.create(
            nom="Growth",
            code="growth",
            prix=59.0,
            duree_jours=30,
            actif=True,
        )
        start_trial_for_entreprise(
            entreprise=self.entreprise_trial,
            plan=self.plan,
            utilisateur=self.owner_trial,
            trial_days=7,
        )
        activate_subscription_for_entreprise(
            entreprise=self.entreprise_active,
            plan=self.plan,
            utilisateur=self.owner_active,
        )

    def test_product_policy_levels_match_v1_strategy(self):
        self.assertEqual(get_module_access_level("clients"), ACCESS_TRIAL_OR_ACTIVE)
        self.assertEqual(get_module_access_level("expenses"), ACCESS_TRIAL_OR_ACTIVE)
        self.assertEqual(get_module_access_level("billing"), ACCESS_TRIAL_OR_ACTIVE)
        self.assertEqual(get_module_access_level("accounting"), ACCESS_ACTIVE_ONLY)
        self.assertEqual(get_module_access_level("apprenants"), ACCESS_TRIAL_OR_ACTIVE)

    def test_trial_can_access_trial_or_active_modules(self):
        self.assertTrue(can_access_module(self.owner_trial, "clients"))
        self.assertTrue(can_access_module(self.owner_trial, "expenses"))
        self.assertTrue(can_access_module(self.owner_trial, "billing"))
        self.assertTrue(can_access_module(self.owner_trial, "apprenants"))
        self.assertFalse(can_access_module(self.owner_trial, "accounting"))

    def test_active_can_access_all_targeted_modules(self):
        self.assertTrue(can_access_module(self.owner_active, "clients"))
        self.assertTrue(can_access_module(self.owner_active, "expenses"))
        self.assertTrue(can_access_module(self.owner_active, "billing"))
        self.assertTrue(can_access_module(self.owner_active, "accounting"))
        self.assertTrue(can_access_module(self.owner_active, "apprenants"))

    def test_missing_subscription_blocks_protected_modules(self):
        self.assertFalse(can_access_module(self.owner_none, "clients"))
        self.assertFalse(can_access_module(self.owner_none, "billing"))

    def test_clients_view_is_allowed_in_trial(self):
        self.client.force_login(self.gestionnaire_trial)
        response = self.client.get(reverse("client_list"))
        self.assertEqual(response.status_code, 200)

    def test_depenses_view_is_allowed_in_trial(self):
        self.client.force_login(self.gestionnaire_trial)
        response = self.client.get(reverse("depenses"))
        self.assertEqual(response.status_code, 200)

    def test_billing_view_is_allowed_in_trial(self):
        self.client.force_login(self.gestionnaire_trial)
        response = self.client.get(reverse("facture_list"))
        self.assertEqual(response.status_code, 200)

    def test_accounting_view_is_refused_in_trial(self):
        self.client.force_login(self.comptable_trial)
        response = self.client.get(reverse("compta_dashboard"))
        self.assertRedirects(response, reverse("abonnement_expire") + "?module=accounting&reason=active_subscription_required")

    def test_accounting_view_is_allowed_when_active(self):
        comptable_active = create_user("compta-active", "comptable", self.entreprise_active)
        self.client.force_login(comptable_active)
        response = self.client.get(reverse("compta_dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_apprenants_view_is_allowed_in_trial(self):
        self.client.force_login(self.gestionnaire_trial)
        response = self.client.get(reverse("apprenant_list"))
        self.assertEqual(response.status_code, 200)

    def test_expired_or_suspended_subscription_blocks_targeted_views(self):
        suspend_subscription_for_entreprise(entreprise=self.entreprise_active, utilisateur=self.owner_active)
        self.client.force_login(self.gestionnaire_active)
        response = self.client.get(reverse("client_list"))
        self.assertRedirects(response, reverse("abonnement_expire") + "?module=clients&reason=inactive_subscription")

    def test_subscription_isolation_is_kept_per_entreprise(self):
        self.client.force_login(self.owner_none)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertRedirects(response, reverse("abonnement_expire") + "?module=dashboard&reason=missing_subscription")


class UserManagementTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Utilisateurs")
        self.autre_entreprise = create_entreprise("Entreprise Externe")
        self.owner = create_user("owner-users", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("gestion-users", "gestionnaire", self.entreprise)
        self.comptable = create_user("compta-users", "comptable", self.entreprise)
        self.external_user = create_user("external-users", "gestionnaire", self.autre_entreprise)
        self.plan = Abonnement.objects.create(
            nom="Users",
            code="users",
            prix=15.0,
            duree_jours=30,
            actif=True,
        )
        start_trial_for_entreprise(
            entreprise=self.entreprise,
            plan=self.plan,
            utilisateur=self.owner,
            trial_days=14,
        )
        start_trial_for_entreprise(
            entreprise=self.autre_entreprise,
            plan=self.plan,
            utilisateur=self.external_user,
            trial_days=14,
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

    def test_user_form_renders_premium_layout(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("user_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Repère rapide")
        self.assertContains(response, "Nom complet")
        self.assertContains(response, "Rôles gérés : Gestionnaire / Comptable")

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
