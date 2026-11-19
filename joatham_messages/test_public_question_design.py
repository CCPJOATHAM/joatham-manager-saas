from django.conf import settings
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import PublicQuestion


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PublicQuestionDesignTests(TestCase):
    payload = {
        "nom": "Élodie Français",
        "email": "elodie@example.com",
        "telephone": "+243 123456",
        "entreprise": "Société Àvenir",
        "sujet": "Facturation en français",
        "message": "Puis-je conserver mes documents en français ?",
    }

    def set_language(self, language):
        response = self.client.post(reverse("set_language"), {
            "language": language, "next": reverse("public_question_create"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.cookies[settings.LANGUAGE_COOKIE_NAME].value, language)

    def test_bilingual_page_preserves_fields_labels_privacy_and_language(self):
        for language, title, privacy in (
            ("fr", "Une question avant de créer votre compte ?", "Nous ne partageons pas votre demande"),
            ("en", "Any questions before you create your account?", "We do not share your request"),
        ):
            with self.subTest(language=language):
                self.set_language(language)
                response = self.client.get(reverse("public_question_create"))
                self.assertContains(response, f'<html lang="{language}">')
                self.assertContains(response, title)
                self.assertContains(response, privacy)
                self.assertContains(response, "joatham_dashboard/img/login-logo.webp")
                self.assertContains(response, f'value="{language}" aria-label=')
                form = response.context["form"]
                self.assertEqual([f.name for f in form.visible_fields()], ["nom", "email", "telephone", "entreprise", "sujet", "message"])
                self.assertEqual([f.name for f in form.hidden_fields()], ["site_web"])
                for field in form.visible_fields():
                    self.assertContains(response, f'for="{field.id_for_label}"')
                for field, autocomplete in (("nom", "name"), ("email", "email"), ("telephone", "tel"), ("entreprise", "organization")):
                    self.assertEqual(form.fields[field].widget.attrs["autocomplete"], autocomplete)

    def test_bilingual_invalid_post_exposes_errors_and_preserves_entered_data(self):
        for language in ("fr", "en"):
            with self.subTest(language=language):
                self.set_language(language)
                response = self.client.post(reverse("public_question_create"), {**self.payload, "telephone": "invalide"})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id="question-errors" tabindex="-1"')
                self.assertContains(response, 'href="#id_telephone"')
                self.assertContains(response, 'aria-invalid="true"')
                self.assertContains(response, 'aria-describedby="id_telephone_error"')
                for field, value in self.payload.items():
                    if field != "telephone":
                        self.assertEqual(response.context["form"][field].value(), value)
                self.assertFalse(PublicQuestion.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_bilingual_submission_preserves_customer_content_and_notification(self):
        from unittest.mock import patch

        for language in ("fr", "en"):
            with self.subTest(language=language):
                self.set_language(language)
                with patch("joatham_messages.services.messages._get_super_admin_recipients", return_value=["admin@example.com"]):
                    response = self.client.post(reverse("public_question_create"), self.payload)
                self.assertRedirects(response, reverse("public_question_success"))
                question = PublicQuestion.objects.latest("pk")
                for field, value in self.payload.items():
                    self.assertEqual(getattr(question, field), value)
                self.assertEqual(mail.outbox[-1].to, ["admin@example.com"])
                self.assertIn(self.payload["message"], mail.outbox[-1].body)
        self.assertEqual(PublicQuestion.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 2)

    def test_honeypot_and_csrf_still_reject_submission(self):
        for language in ("fr", "en"):
            with self.subTest(language=language):
                self.set_language(language)
                response = self.client.post(reverse("public_question_create"), {**self.payload, "site_web": "https://spam.example.com"})
                self.assertEqual(response.status_code, 200)
                self.assertIn("site_web", response.context["form"].errors)
                response = Client(enforce_csrf_checks=True).post(reverse("public_question_create"), self.payload)
                self.assertEqual(response.status_code, 403)
                self.assertFalse(PublicQuestion.objects.exists())
