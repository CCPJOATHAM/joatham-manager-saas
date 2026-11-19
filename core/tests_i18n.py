import io
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from pypdf import PdfReader

from core.i18n_audit import catalog_state, catalog_errors, python_errors, template_errors
from core.models import ActivityLog
from core.services.currency import format_decimal_number
from core.services.language import LANGUAGE_SESSION_KEY
from core.services.subscription import activate_subscription_for_entreprise, get_default_paid_plans
from joatham_billing.tests.factories import create_client, create_entreprise, create_facture_sample, create_user
from joatham_users.models import Abonnement, User
from joatham_clients.models import Client


class TranslationCoverageTests(SimpleTestCase):
    def test_invitation_email_keeps_recipient_and_activation_link_in_both_languages(self):
        activation_url = "https://example.invalid/activate/unchanged-token/"
        context = {
            "invitation": SimpleNamespace(full_name="Élodie Martin", email="elodie@example.invalid", expires_at=timezone.now()),
            "activation_url": activation_url,
            "support_email": "support@example.invalid",
            "app_url": "https://example.invalid/",
        }
        for language in ("fr", "en"):
            with self.subTest(language=language), translation.override(language):
                body = render_to_string("joatham_users/emails/invitation_reminder.txt", context)
                self.assertIn("Élodie Martin", body)
                self.assertIn(activation_url, body)
                if language == "en":
                    self.assertIn("Your JOATHAM Manager account is ready.", body)
                    self.assertIn("accounting for your business.", body)
                else:
                    self.assertNotIn("Your JOATHAM Manager account is ready.", body)

    def test_catalog_comparison_ignores_order_but_detects_content_changes(self):
        first = 'msgid "Connexion"\nmsgstr "Sign in"\n\n'
        second = 'msgctxt "billing"\nmsgid "Facture"\nmsgstr "Invoice"\n\n'
        with TemporaryDirectory() as directory:
            original, extracted = Path(directory) / "original.po", Path(directory) / "extracted.po"
            original.write_text(first + second, encoding="utf-8")
            extracted.write_text(second + first, encoding="utf-8")
            self.assertEqual(catalog_state(original), catalog_state(extracted))
            for changed in (
                second.replace("Invoice", "Bill") + first,
                '#, fuzzy\n' + second + first,
                first,
            ):
                extracted.write_text(changed, encoding="utf-8")
                self.assertNotEqual(catalog_state(original), catalog_state(extracted))

    def test_both_catalogs_are_complete(self):
        self.assertEqual(catalog_errors(), [])

    def test_all_templates_compile_and_visible_labels_are_marked(self):
        self.assertEqual(template_errors(), [])

    def test_python_messages_and_form_labels_are_marked(self):
        self.assertEqual(python_errors(), [])

    def test_money_format_follows_active_language(self):
        for language, expected in (("fr", "1 234,50"), ("en", "1,234.50")):
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(format_decimal_number(Decimal("1234.5")), expected)

    def test_saved_system_activity_translates_without_changing_customer_text(self):
        log = ActivityLog(action="facture_creee", module="billing",
                          description="Facture F-001 creee pour Société française.")
        original = log.description
        with translation.override("en"):
            self.assertEqual(log.display_action, "Invoice created")
            self.assertEqual(log.display_module, "Billing")
            self.assertEqual(log.display_description, "Invoice F-001 created for Société française.")
        with translation.override("fr"):
            self.assertEqual(log.display_action, "Facture créée")
        self.assertEqual(log.description, original)
        log.description = "Commentaire libre de Société française"
        with translation.override("en"):
            self.assertEqual(log.display_description, log.description)


class BilingualJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = create_entreprise("Entreprise cliente française")
        cls.owner = create_user("bilingual-owner", "proprietaire", cls.company)
        premium = next(plan for plan in get_default_paid_plans() if plan["code"] == "premium")
        plan = Abonnement.objects.create(**premium, actif=True)
        activate_subscription_for_entreprise(
            entreprise=cls.company, plan=plan, utilisateur=cls.owner
        )
        cls.customer = create_client(cls.company, "Client français conservé")
        cls.invoice = create_facture_sample(cls.company, cls.owner, cls.customer)

    def switch_language(self, language, next_route="admin_dashboard"):
        response = self.client.post(
            reverse("set_language"),
            {"language": language, "next": reverse(next_route)},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[LANGUAGE_SESSION_KEY], language)
        return response

    def test_unpaid_invoice_summary_keeps_outstanding_meaning_and_plurals(self):
        self.client.force_login(self.owner)
        self.switch_language("en")
        response = self.client.get(reverse("facture_list"))
        self.assertContains(response, "1 outstanding invoice")
        self.assertNotContains(response, "not outstanding")
        create_facture_sample(self.company, self.owner, self.customer)
        response = self.client.get(reverse("facture_list"))
        self.assertContains(response, "2 outstanding invoices")
        self.assertContains(response, "Client français conservé")

    def test_main_modules_render_in_both_languages(self):
        routes = (
            "admin_dashboard", "client_list", "facture_list", "proforma_list",
            "depenses", "caisse_list", "product_list", "apprenant_list",
            "compta_dashboard", "rh_employe_list", "message_conversation_list",
            "profile",
        )
        self.client.force_login(self.owner)
        for language in ("fr", "en"):
            self.switch_language(language)
            for route in routes:
                with self.subTest(language=language, route=route):
                    response = self.client.get(reverse(route))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response["Content-Language"], language)
                    self.assertContains(response, f'<html lang="{language}"')
                    self.assertNotContains(response, "{% trans")
            customers = self.client.get(reverse("client_list"))
            self.assertContains(customers, "Client français conservé")
            dashboard = self.client.get(reverse("admin_dashboard"))
            self.assertContains(dashboard, "Entreprise cliente française")
        self.company.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(self.company.nom, "Entreprise cliente française")
        self.assertEqual(self.customer.nom, "Client français conservé")

    def test_language_persists_on_profile_and_new_session(self):
        self.client.force_login(self.owner)
        self.switch_language("en")
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.preferred_language, "en")
        self.client.logout()
        self.client.force_login(self.owner)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(response["Content-Language"], "en")
        self.assertContains(response, "Executive dashboard")

    def test_public_cookie_login_and_javascript_catalog_follow_language(self):
        for language in ("fr", "en"):
            self.switch_language(language, "login")
            self.assertEqual(self.client.cookies[settings.LANGUAGE_COOKIE_NAME].value, language)
            response = self.client.get(reverse("login"))
            self.assertContains(response, "Connexion" if language == "fr" else "Sign in")
            javascript = self.client.get(reverse("javascript_catalog"))
            self.assertEqual(javascript.status_code, 200)
            self.assertEqual(javascript["Content-Language"], language)
            self.assertIn("no-cache", javascript["Cache-Control"])
            self.assertContains(javascript, "Rupture de stock" if language == "fr" else "Out of stock")

    def test_manager_and_accountant_dashboards_follow_language(self):
        for role, route in (("gestionnaire", "gestion_dashboard"), ("comptable", "comptable_dashboard")):
            user = create_user("bilingual-" + role, role, self.company)
            self.client.force_login(user)
            for language in ("fr", "en"):
                self.switch_language(language, route)
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Language"], language)
                if role == "gestionnaire":
                    self.assertContains(response, "Daily operations" if language == "en" else "Pilotage quotidien")
                else:
                    self.assertContains(response, "Financial control" if language == "en" else "Contrôle financier")

    def test_customer_input_is_preserved_during_english_submission(self):
        self.client.force_login(self.owner)
        self.switch_language("en")
        response = self.client.post(reverse("add_client"), {
            "nom": "Société française à préserver",
            "telephone": "+243000000000",
            "email": "client@example.invalid",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Société française à préserver")
        self.assertEqual(Client.objects.filter(entreprise=self.company, nom="Société française à préserver").count(), 1)

    def test_super_admin_pages_render_in_both_languages(self):
        admin = User.objects.create_user(
            username="bilingual-platform", password="testpass123",
            role="super_admin", is_staff=True, is_superuser=True,
        )
        self.client.force_login(admin)
        for language in ("fr", "en"):
            self.switch_language(language, "super_admin_dashboard")
            for route in (
                "super_admin_dashboard", "super_admin_company_list",
                "super_admin_user_list", "super_admin_subscription_list",
                "super_admin_exchange_rate_list",
            ):
                with self.subTest(language=language, route=route):
                    response = self.client.get(reverse(route))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response["Content-Language"], language)

    def test_invoice_pdf_labels_and_customer_data_in_both_languages(self):
        self.client.force_login(self.owner)
        for language, invoice_label in (("fr", "Facture"), ("en", "Invoice")):
            self.switch_language(language)
            response = self.client.get(reverse("facture_pdf", args=[self.invoice.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            contents = b"".join(response.streaming_content) if response.streaming else response.content
            text = " ".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(contents)).pages)
            self.assertIn(invoice_label.upper(), text.upper())
            self.assertIn("Client français conservé", text)
