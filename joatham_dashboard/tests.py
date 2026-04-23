from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from core.models import ActivityLog
from core.services.subscription import activate_subscription_for_entreprise
from core.services.world import get_default_currency_for_country
from joatham_billing.tests.factories import create_client, create_entreprise, create_facture_sample, create_user
from joatham_depenses.models import Depense
from joatham_products.models import Produit
from joatham_users.models import Abonnement, AbonnementEntreprise, Entreprise, User
from .services.email_verification import email_verification_token_generator

from .selectors.dashboard import get_dashboard_kpis_by_entreprise
from .services.dashboard_service import build_dashboard_context


class DashboardAccessTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Dashboard")
        self.entreprise_b = create_entreprise("Entreprise Dashboard B")
        self.proprietaire = create_user("owner-dash", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("gestion-dash", "gestionnaire", self.entreprise)
        self.comptable = create_user("compta-dash", "comptable", self.entreprise)
        self.gestionnaire_b = create_user("gestion-dash-b", "gestionnaire", self.entreprise_b)
        self.plan = Abonnement.objects.create(nom="Dash", code="dash", prix=10.0, duree_jours=30, actif=True)
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.proprietaire)
        activate_subscription_for_entreprise(entreprise=self.entreprise_b, plan=self.plan, utilisateur=self.gestionnaire_b)
        self.client_a = create_client(self.entreprise, "Client Dashboard A")
        self.client_b = create_client(self.entreprise_b, "Client Dashboard B")
        create_facture_sample(self.entreprise, self.gestionnaire, self.client_a, Decimal("100"))
        create_facture_sample(self.entreprise_b, self.gestionnaire_b, self.client_b, Decimal("70"))
        Depense.objects.create(description="Internet", montant=Decimal("20"), entreprise=self.entreprise)
        Depense.objects.create(description="Transport", montant=Decimal("15"), entreprise=self.entreprise_b)
        self.rupture_product = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Imprimante A4",
            description="Imprimante laser",
            reference="PRD-IMPR-1",
            prix_unitaire=Decimal("250"),
            quantite_stock=0,
            seuil_alerte=2,
            actif=True,
        )
        self.low_stock_product = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Routeur fibre",
            description="Routeur bureau",
            reference="PRD-ROUT-1",
            prix_unitaire=Decimal("120"),
            quantite_stock=2,
            seuil_alerte=5,
            actif=True,
        )
        Produit.objects.create(
            entreprise=self.entreprise_b,
            nom="Stock B",
            description="Produit B",
            reference="PRD-B-1",
            prix_unitaire=Decimal("50"),
            quantite_stock=0,
            seuil_alerte=3,
            actif=True,
        )

    def test_login_redirects_to_role_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {"username": "owner-dash", "password": "testpass123"},
        )
        self.assertRedirects(response, reverse("admin_dashboard"))

    def test_login_page_contains_branding_and_password_toggle(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "JOATHAM Manager")
        self.assertContains(response, "togglePassword")
        self.assertContains(response, reverse("signup"))

    def test_logout_route_disconnects_and_redirects_to_login(self):
        self.client.force_login(self.proprietaire)
        response = self.client.get(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        login_page = self.client.get(reverse("login"))
        self.assertEqual(login_page.status_code, 200)

    def test_gestionnaire_cannot_access_owner_dashboard(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_comptable_can_access_own_dashboard(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("comptable_dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_selector_is_scoped_to_entreprise(self):
        kpis = get_dashboard_kpis_by_entreprise(self.entreprise)
        self.assertEqual(kpis["nombre_factures"], 1)
        self.assertEqual(kpis["nombre_clients"], 1)
        self.assertEqual(kpis["payees"], 0)
        self.assertEqual(kpis["impayees"], 1)
        self.assertEqual(kpis["total_ca"], Decimal("100"))
        self.assertEqual(kpis["total_depenses"], Decimal("20"))
        self.assertEqual(kpis["benefice"], Decimal("80"))
        self.assertEqual(kpis["total_encaisse"], Decimal("0"))
        self.assertEqual(kpis["reste_encaisser"], Decimal("116"))

    def test_dashboard_service_formats_kpis_for_templates(self):
        context = build_dashboard_context(self.entreprise)
        self.assertEqual(context["total_ca"], "100,00 CDF")
        self.assertEqual(context["total_depenses"], "20,00 CDF")
        self.assertEqual(context["benefice"], "80,00 CDF")
        self.assertEqual(context["nombre_factures"], 1)
        self.assertEqual(context["nombre_clients"], 1)
        self.assertEqual(context["reste_encaisser"], "116,00 CDF")
        self.assertEqual(context["rupture_products_count"], 1)
        self.assertEqual(context["low_stock_products_count"], 1)

    def test_dashboard_view_context_is_isolated_per_entreprise(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("gestion_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_ca"], "100,00 CDF")
        self.assertEqual(response.context["total_depenses"], "20,00 CDF")
        self.assertEqual(response.context["nombre_factures"], 1)
        self.assertEqual(response.context["nombre_clients"], 1)
        self.assertContains(response, "Pilotage quotidien")
        self.assertContains(response, "Reste a relancer")

    def test_owner_navigation_contains_admin_links(self):
        self.client.force_login(self.proprietaire)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(response, reverse("company_settings"))
        self.assertContains(response, reverse("user_list"))
        self.assertContains(response, reverse("user_create"))
        self.assertContains(response, reverse("subscription_overview"))
        self.assertContains(response, reverse("activity_log_list"))
        self.assertContains(response, "Bienvenue dans votre cockpit JOATHAM Manager")
        self.assertContains(response, "Activite recente")
        self.assertContains(response, "Alertes stock")
        self.assertContains(response, "Imprimante A4")
        self.assertContains(response, "Routeur fibre")
        self.assertContains(response, reverse("product_list"))

    def test_dashboard_selector_detects_stock_alerts_with_company_isolation(self):
        kpis = get_dashboard_kpis_by_entreprise(self.entreprise)
        self.assertEqual(kpis["rupture_products_count"], 1)
        self.assertEqual(kpis["low_stock_products_count"], 1)
        self.assertEqual([product.nom for product in kpis["rupture_products"]], ["Imprimante A4"])
        self.assertEqual([product.nom for product in kpis["low_stock_products"]], ["Routeur fibre"])

    def test_gestionnaire_navigation_hides_owner_only_links(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("gestion_dashboard"))
        self.assertNotContains(response, reverse("company_settings"))
        self.assertNotContains(response, reverse("subscription_overview"))
        self.assertNotContains(response, reverse("activity_log_list"))

    def test_comptable_navigation_hides_owner_only_links(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("comptable_dashboard"))
        self.assertNotContains(response, reverse("company_settings"))
        self.assertNotContains(response, reverse("subscription_overview"))
        self.assertNotContains(response, reverse("activity_log_list"))
        self.assertContains(response, "Vue de controle financier")
        self.assertContains(response, "Montants dus")
        self.assertContains(response, "Origine recente des flux")
        self.assertContains(response, self.gestionnaire.username)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class OnboardingSignupTests(TestCase):
    def test_signup_page_is_available(self):
        response = self.client.get(reverse("signup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inscription entreprise")
        self.assertContains(response, "Creer mon entreprise")

    def test_authenticated_user_is_redirected_from_signup(self):
        entreprise = create_entreprise("Entreprise Connectee")
        owner = create_user("owner-connected", "proprietaire", entreprise)
        self.client.force_login(owner)
        response = self.client.get(reverse("signup"))
        self.assertRedirects(response, reverse("admin_dashboard"), fetch_redirect_response=False)

    def test_signup_creates_owner_entreprise_and_trial(self):
        response = self.client.post(
            reverse("signup"),
            {
                "company_name": "Entreprise Monde",
                "raison_sociale": "Entreprise Monde SARL",
                "owner_full_name": "Alice Monde",
                "email": "alice@example.com",
                "telephone": "+243900000010",
                "pays": "Angola",
                "devise": "AOA",
                "password": "Motdepasse123!",
                "password_confirm": "Motdepasse123!",
            },
        )

        self.assertRedirects(response, reverse("email_verification_sent"))
        user = User.objects.get(email="alice@example.com")
        entreprise = Entreprise.objects.get(id=user.entreprise_id)
        subscription = AbonnementEntreprise.objects.get(entreprise=entreprise)

        self.assertEqual(user.role, "proprietaire")
        self.assertEqual(user.username, "alice@example.com")
        self.assertFalse(user.email_verified)
        self.assertEqual(entreprise.nom, "Entreprise Monde")
        self.assertEqual(entreprise.pays, "Angola")
        self.assertEqual(entreprise.devise, "AOA")
        self.assertEqual(subscription.statut, AbonnementEntreprise.Statut.ESSAI)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("email-verification/confirm/", mail.outbox[0].body)

    def test_signup_rejects_duplicate_email_and_prompts_login(self):
        entreprise = create_entreprise("Entreprise Existante")
        create_user("owner-existing", "proprietaire", entreprise).email = "owner@example.com"
        existing_user = User.objects.get(username="owner-existing")
        existing_user.email = "owner@example.com"
        existing_user.save(update_fields=["email"])

        response = self.client.post(
            reverse("signup"),
            {
                "company_name": "Nouvelle Entreprise",
                "raison_sociale": "",
                "owner_full_name": "Bob Test",
                "email": "owner@example.com",
                "telephone": "+243900000011",
                "pays": "France",
                "devise": "EUR",
                "password": "Motdepasse123!",
                "password_confirm": "Motdepasse123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Un compte existe déjà avec cet e-mail. Veuillez vous connecter.")
        self.assertContains(response, reverse("login"))

    def test_country_currency_mapping_covers_requested_examples(self):
        self.assertEqual(get_default_currency_for_country("Angola"), "AOA")
        self.assertEqual(get_default_currency_for_country("RDC"), "CDF")
        self.assertEqual(get_default_currency_for_country("Congo-Brazzaville"), "XAF")
        self.assertEqual(get_default_currency_for_country("Nigeria"), "NGN")
        self.assertEqual(get_default_currency_for_country("Etats-Unis"), "USD")

    def test_unverified_user_cannot_login_to_platform_until_email_is_confirmed(self):
        entreprise = create_entreprise("Entreprise Email")
        user = create_user("owner-email", "proprietaire", entreprise)
        user.email = "owner-email@example.com"
        user.email_verified = False
        user.save(update_fields=["email", "email_verified"])

        response = self.client.post(
            reverse("login"),
            {"username": "owner-email@example.com", "password": "testpass123"},
        )

        self.assertRedirects(response, reverse("email_verification_sent"))
        blocked = self.client.get(reverse("admin_dashboard"))
        self.assertRedirects(
            blocked,
            f"/accounts/login/?next={reverse('admin_dashboard')}",
            fetch_redirect_response=False,
        )

    def test_email_confirmation_allows_normal_login_after_success(self):
        response = self.client.post(
            reverse("signup"),
            {
                "company_name": "Entreprise Validation",
                "raison_sociale": "",
                "owner_full_name": "Claire Validation",
                "email": "claire@example.com",
                "telephone": "+243900000012",
                "pays": "RDC",
                "devise": "CDF",
                "password": "Motdepasse123!",
                "password_confirm": "Motdepasse123!",
            },
        )
        self.assertRedirects(response, reverse("email_verification_sent"))

        user = User.objects.get(email="claire@example.com")
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_verification_token_generator.make_token(user)
        confirm_response = self.client.get(reverse("email_verification_confirm", args=[uidb64, token]))
        self.assertEqual(confirm_response.status_code, 200)

        user.refresh_from_db()
        self.assertTrue(user.email_verified)

        login_response = self.client.post(
            reverse("login"),
            {"username": "claire@example.com", "password": "Motdepasse123!"},
        )
        self.assertRedirects(login_response, reverse("admin_dashboard"))

    def test_invalid_email_confirmation_link_is_rejected(self):
        entreprise = create_entreprise("Entreprise Invalide")
        user = create_user("owner-invalid", "proprietaire", entreprise)
        user.email = "invalid@example.com"
        user.email_verified = False
        user.save(update_fields=["email", "email_verified"])

        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        response = self.client.get(reverse("email_verification_confirm", args=[uidb64, "bad-token"]))
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Lien de confirmation invalide ou expiré", status_code=400)

    def test_email_verification_resend_sends_new_email(self):
        response = self.client.post(
            reverse("signup"),
            {
                "company_name": "Entreprise Renvoi",
                "raison_sociale": "",
                "owner_full_name": "Daniel Renvoi",
                "email": "daniel@example.com",
                "telephone": "+243900000013",
                "pays": "RDC",
                "devise": "CDF",
                "password": "Motdepasse123!",
                "password_confirm": "Motdepasse123!",
            },
        )
        self.assertRedirects(response, reverse("email_verification_sent"))
        self.assertEqual(len(mail.outbox), 1)

        resend_response = self.client.post(reverse("email_verification_resend"))
        self.assertRedirects(resend_response, reverse("email_verification_sent"))
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(EMAIL_VERIFICATION_TIMEOUT=3600)
    def test_email_verification_token_stays_valid_for_normal_delay(self):
        entreprise = create_entreprise("Entreprise Timeout")
        user = create_user("owner-timeout", "proprietaire", entreprise)
        user.email = "timeout@example.com"
        user.email_verified = False
        user.save(update_fields=["email", "email_verified"])

        base_time = datetime.now()
        with patch.object(email_verification_token_generator, "_now", return_value=base_time):
            token = email_verification_token_generator.make_token(user)

        with patch.object(email_verification_token_generator, "_now", return_value=base_time + timedelta(minutes=1)):
            self.assertTrue(email_verification_token_generator.check_token(user, token))

    @override_settings(EMAIL_VERIFICATION_TIMEOUT=1)
    def test_email_verification_token_expires_after_configured_timeout(self):
        entreprise = create_entreprise("Entreprise Expire")
        user = create_user("owner-expire", "proprietaire", entreprise)
        user.email = "expire@example.com"
        user.email_verified = False
        user.save(update_fields=["email", "email_verified"])

        base_time = datetime.now()
        with patch.object(email_verification_token_generator, "_now", return_value=base_time):
            token = email_verification_token_generator.make_token(user)

        with patch.object(email_verification_token_generator, "_now", return_value=base_time + timedelta(seconds=2)):
            self.assertFalse(email_verification_token_generator.check_token(user, token))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.entreprise = create_entreprise("Entreprise Reset")
        self.user = create_user("owner-reset", "proprietaire", self.entreprise)
        self.user.email = "owner-reset@example.com"
        self.user.save(update_fields=["email"])

    def test_password_reset_request_uses_neutral_message_for_unknown_email(self):
        response = self.client.post(reverse("password_reset"), {"email": "unknown@example.com"})

        self.assertRedirects(response, reverse("password_reset_done"))
        done = self.client.get(reverse("password_reset_done"))
        self.assertContains(done, "Si un compte existe avec cet email")
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_request_sends_email_and_creates_audit_for_known_email(self):
        response = self.client.post(reverse("password_reset"), {"email": "owner-reset@example.com"})

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("reset/", mail.outbox[0].body)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.user,
                action="password_reset_requested",
                module="auth",
            ).exists()
        )

    def test_password_reset_confirm_updates_password_and_audits_completion(self):
        self.client.post(reverse("password_reset"), {"email": "owner-reset@example.com"})
        email_body = mail.outbox[0].body
        reset_path = email_body.split("http://testserver", 1)[1].splitlines()[0].strip()
        confirm_response = self.client.get(reset_path)
        final_reset_path = confirm_response.url or reset_path

        response = self.client.post(
            final_reset_path,
            {
                "new_password1": "NouveauMotdepasse123!",
                "new_password2": "NouveauMotdepasse123!",
            },
        )

        self.assertRedirects(response, reverse("password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NouveauMotdepasse123!"))
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.user,
                action="password_reset_completed",
                module="auth",
            ).exists()
        )

    @override_settings(PASSWORD_RESET_REQUEST_COOLDOWN=60)
    def test_password_reset_request_is_throttled_without_leaking_information(self):
        first = self.client.post(reverse("password_reset"), {"email": "owner-reset@example.com"})
        second = self.client.post(reverse("password_reset"), {"email": "owner-reset@example.com"})

        self.assertRedirects(first, reverse("password_reset_done"))
        self.assertRedirects(second, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

    def test_password_reset_complete_page_redirects_to_login(self):
        response = self.client.get(reverse("password_reset_complete"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'http-equiv="refresh"')
        self.assertContains(response, reverse("login"))

    def test_password_reset_rejects_weak_password(self):
        self.client.post(reverse("password_reset"), {"email": "owner-reset@example.com"})
        email_body = mail.outbox[0].body
        reset_path = email_body.split("http://testserver", 1)[1].splitlines()[0].strip()
        confirm_response = self.client.get(reset_path)
        final_reset_path = confirm_response.url or reset_path

        response = self.client.post(
            final_reset_path,
            {
                "new_password1": "simple",
                "new_password2": "simple",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "au moins une lettre majuscule")
