"""Authorization tests use only generated files under a temporary MEDIA_ROOT."""
from pathlib import Path
import runpy
import tempfile
from types import ModuleType

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import PaiementAbonnement
from core.services.company_deletion import cancel_deletion, schedule_deletion
from core.services.subscription import activate_free_plan_for_entreprise, activate_subscription_for_entreprise, get_default_paid_plans
from core.file_widgets import MessageAttachmentInput
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_messages.models import MessageAttachment
from joatham_messages.services.messages import create_conversation
from joatham_payments.models import PaymentTransaction
from joatham_users.forms import ProfileUpdateForm
from joatham_users.models import Abonnement, User


class PrivateMediaTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.media = Path(temporary.name)
        self.settings_override = override_settings(MEDIA_ROOT=self.media, DEBUG=True)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        # Execute the real URL configuration against the temporary storage;
        # do not reuse the document_root captured at the first module import.
        urls = runpy.run_path(str(settings.BASE_DIR / "joatham_pro" / "urls.py"))
        urlconf = ModuleType("private_media_test_urls")
        urlconf.urlpatterns = urls["urlpatterns"]
        self.url_override = override_settings(ROOT_URLCONF=urlconf)
        self.url_override.enable()
        self.addCleanup(self.url_override.disable)
        self.company = create_entreprise("Private files A")
        self.other = create_entreprise("Private files B")
        self.owner = create_user("files-owner", "proprietaire", self.company)
        self.other_owner = create_user("files-other", "proprietaire", self.other)
        self.nonparticipant = create_user("files-nonparticipant", "proprietaire", self.company)
        self.admin = User.objects.create_user(username="files-platform", role="super_admin", password="testpass123")
        premium = next(p for p in get_default_paid_plans() if p["code"] == "premium")
        self.plan = Abonnement.objects.create(**premium, actif=True)
        for company, owner in ((self.company, self.owner), (self.other, self.other_owner)):
            activate_subscription_for_entreprise(entreprise=company, plan=self.plan, utilisateur=owner)
        self.payment = PaymentTransaction.objects.create(
            entreprise=self.company, amount=12, attachment=self.upload("payment.txt"),
        )
        self.evidence = PaiementAbonnement.objects.create(
            entreprise=self.company, plan=self.plan, duree="mensuel", montant=12,
            reference_paiement="FAKE-ONLY", preuve_paiement=self.upload("evidence.txt"),
        )
        conversation = create_conversation(
            entreprise=self.company, creator=self.owner, subject="Private fixture",
            participant_ids=[], content="Fixture", attachments=[self.upload("message.txt")],
        )
        self.attachment = MessageAttachment.objects.get(message__conversation=conversation)
        self.owner.profile_photo.save("avatar.png", self.upload("avatar.png"))
        self.company.logo.save("logo.png", self.upload("logo.png"))
        self.routes = (
            reverse("payment_attachment", args=[self.payment.pk]),
            reverse("subscription_payment_evidence", args=[self.evidence.pk]),
            reverse("message_attachment_download", args=[self.attachment.pk]),
        )

    @staticmethod
    def upload(name):
        return SimpleUploadedFile(name, b"FICTIONAL PRIVATE CONTENT", content_type="text/plain")

    def login(self, user, language):
        user.preferred_language = language
        user.save(update_fields=["preferred_language"])
        self.client.force_login(user)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = language

    def assert_download(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(b"".join(response.streaming_content), b"FICTIONAL PRIVATE CONTENT")

    def test_owner_can_download_in_both_languages(self):
        for language in ("fr", "en"):
            self.login(self.owner, language)
            for url in self.routes:
                with self.subTest(language=language, url=url):
                    response = self.client.get(url)
                    self.assertIn("attachment;", response["Content-Disposition"])
                    self.assert_download(response)

    def test_anonymous_cannot_download(self):
        for language in ("fr", "en"):
            self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
            for url in (*self.routes, reverse("own_profile_photo")):
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_other_company_cannot_download_even_with_known_object_ids(self):
        for language in ("fr", "en"):
            self.login(self.other_owner, language)
            for url in self.routes:
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_same_company_nonparticipant_cannot_download_message(self):
        self.login(self.nonparticipant, "en")
        self.assertEqual(self.client.get(self.routes[2]).status_code, 404)

    def test_pending_deletion_blocks_old_session_and_new_sessions(self):
        self.login(self.owner, "fr")
        schedule_deletion(company_id=self.company.pk, actor=self.admin,
                          confirmation_name=self.company.nom, reason="Fictitious privacy test")
        # A legacy reactivation must not reopen a pending tenant's files.
        type(self.company).objects.filter(pk=self.company.pk).update(is_active=True)
        self.assertEqual(self.client.get(self.routes[0]).status_code, 403)
        for language in ("fr", "en"):
            for url in (*self.routes, reverse("own_profile_photo")):
                self.login(self.owner, language)
                self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        for field in (self.payment.attachment, self.evidence.preuve_paiement, self.attachment.fichier):
            self.assertEqual(self.client.get(field.url).status_code, 404)

    def test_restoration_reopens_authorized_routes_only(self):
        args = dict(company_id=self.company.pk, actor=self.admin,
                    confirmation_name=self.company.nom, reason="Fictitious recovery test")
        schedule_deletion(**args)
        cancel_deletion(**args)
        self.login(self.owner, "en")
        for url in self.routes:
            self.assert_download(self.client.get(url))
        self.client.logout()
        self.assertEqual(self.client.get(self.payment.attachment.url).status_code, 404)

    def test_subscription_permission_and_payment_module_are_preserved(self):
        manager = create_user("files-manager", "gestionnaire", self.company)
        self.login(manager, "en")
        self.assertEqual(self.client.get(self.routes[1]).status_code, 403)
        activate_free_plan_for_entreprise(entreprise=self.company, utilisateur=self.owner)
        self.login(self.owner, "en")
        self.assertEqual(self.client.get(self.routes[0]).status_code, 302)

    def test_admin_widget_does_not_emit_storage_url(self):
        rendered = MessageAttachmentInput().render("fichier", self.attachment.fichier)
        self.assertIn(self.routes[2], rendered)
        self.assertNotIn(self.attachment.fichier.url, rendered)

    def test_inactive_company_cannot_download(self):
        type(self.company).objects.filter(pk=self.company.pk).update(is_active=False)
        for url in (*self.routes, reverse("own_profile_photo")):
            self.login(self.owner, "en")
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_known_raw_private_paths_are_not_served_even_in_debug(self):
        names = [self.payment.attachment.name, self.evidence.preuve_paiement.name,
                 self.attachment.fichier.name, self.owner.profile_photo.name]
        for user in (None, self.owner, self.other_owner):
            self.client.logout()
            if user:
                self.login(user, "en")
            for name in names:
                self.assertEqual(self.client.get("/media/" + name).status_code, 404)

    def test_logos_remain_public_but_parent_paths_are_not(self):
        response = self.client.get(self.company.logo.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"FICTIONAL PRIVATE CONTENT")
        for path in ("/media/", "/media/entreprises/logos/../../payments/supporting_docs/payment.txt",
                     "/media/entreprises/logos/%2e%2e/%2e%2e/payments/supporting_docs/payment.txt"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_profile_uses_self_only_route_and_preserves_clear_control(self):
        self.login(self.owner, "en")
        self.assert_download(self.client.get(reverse("own_profile_photo")))
        self.login(self.other_owner, "en")
        self.assertEqual(self.client.get(reverse("own_profile_photo")).status_code, 404)
        widget_html = str(ProfileUpdateForm(instance=self.owner)["profile_photo"])
        self.assertIn(reverse("own_profile_photo"), widget_html)
        self.assertIn('name="profile_photo-clear"', widget_html)
        self.assertNotIn(self.owner.profile_photo.url, widget_html)

    def test_payment_page_links_to_authorized_view(self):
        for language in ("fr", "en"):
            self.login(self.owner, language)
            response = self.client.get(reverse("payment_detail", args=[self.payment.pk]))
            self.assertContains(response, self.routes[0])
            self.assertNotContains(response, self.payment.attachment.url)

    def test_missing_file_returns_404_without_storage_path(self):
        self.login(self.owner, "en")
        self.payment.attachment.delete()
        self.assertEqual(self.client.get(self.routes[0]).status_code, 404)
        self.evidence.preuve_paiement.storage.delete(self.evidence.preuve_paiement.name)
        self.assertEqual(self.client.get(self.routes[1]).status_code, 404)

    def test_platform_evidence_access_is_separate(self):
        url = reverse("subscription_payment_evidence_admin", args=[self.evidence.pk])
        self.login(self.owner, "en")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(self.admin, "en")
        self.assert_download(self.client.get(url))
