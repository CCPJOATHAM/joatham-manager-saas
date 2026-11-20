from html.parser import HTMLParser

from django.conf import settings
from django.core import mail
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils.translation import gettext, override

from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_dashboard.services.email_verification import (
    email_verification_token_generator, send_email_verification,
)


class EmailMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.images, self.links = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "img":
            self.images.append(attrs)
        elif tag == "a":
            self.links.append(attrs["href"])


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEBUG=False)
class EmailVerificationDesignTests(TestCase):
    def setUp(self):
        self.user = create_user("verification-design", "proprietaire", create_entreprise("Société Àvenir"))
        self.user.email = "elodie.francais@example.com"
        self.user.first_name = "Élodie"
        self.user.last_name = "Français"
        self.user.email_verified = False
        self.user.save()
        session = self.client.session
        session["pending_verification_user_id"] = self.user.pk
        session["debug_email_verification_url"] = "https://testserver/private-preview"
        session.save()

    def select_language(self, language):
        self.client.post(reverse("set_language"), {"language": language, "next": reverse("email_verification_sent")})

    def test_bilingual_page_preserves_address_expiration_resend_and_debug_protection(self):
        for language in ("fr", "en"):
            for timeout, minutes in ((60, 1), (3600, 60)):
                with self.subTest(language=language, timeout=timeout), override(language), override_settings(EMAIL_VERIFICATION_TIMEOUT=timeout):
                    self.select_language(language)
                    response = self.client.get(reverse("email_verification_sent"))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, f'<html lang="{language}">')
                    self.assertContains(response, gettext("Confirmez votre adresse email"))
                    self.assertContains(response, self.user.email)
                    self.assertEqual(response.context["expiration_minutes"], minutes)
                    self.assertContains(response, 'alt="JOATHAM Manager"')
                    self.assertContains(response, 'joatham_dashboard/img/login-logo.webp')
                    self.assertContains(response, f'action="{reverse("email_verification_resend")}"')
                    self.assertContains(response, 'name="csrfmiddlewaretoken"')
                    self.assertContains(response, f'href="{reverse("login")}"')
                    self.assertNotContains(response, "private-preview")

    def test_bilingual_resend_preserves_multipart_content_and_confirmation_token(self):
        for language in ("fr", "en"):
            with self.subTest(language=language), override(language):
                self.select_language(language)
                response = self.client.post(reverse("email_verification_resend"), secure=True)
                self.assertRedirects(response, reverse("email_verification_sent"))
                email = mail.outbox[-1]
                self.assertEqual(email.to, [self.user.email])
                self.assertEqual(email.subject, gettext("Confirmez votre adresse email | JOATHAM Manager"))
                self.assertEqual(email.alternatives[0].mimetype, "text/html")
                html = email.alternatives[0].content
                markup = EmailMarkup(html)
                url = markup.links[0]
                self.assertIn(url, email.body)
                self.assertEqual(html.count(url), 2)
                self.assertEqual(markup.images[0]["src"], "https://testserver/static/joatham_dashboard/img/email-logo.png")
                self.assertEqual(markup.images[0]["alt"], "JOATHAM Manager")
                self.assertIn("Élodie Français", html)
                self.assertIn("Élodie Français", email.body)
                self.assertEqual(email.body, render_to_string("registration/email_verification_email.txt", {
                    "user": self.user, "verification_url": url,
                    "expiration_seconds": settings.EMAIL_VERIFICATION_TIMEOUT,
                }))
                self.assertNotIn("<img", email.body)
                self.assertIn(str(settings.EMAIL_VERIFICATION_TIMEOUT), html)
                self.assertIn(gettext("Si vous n’êtes pas à l’origine de cette inscription, ignorez simplement cet email."), email.body)
                token = url.rstrip("/").split("/")[-1]
                self.assertTrue(email_verification_token_generator.check_token(self.user, token))
                self.user.refresh_from_db()
                self.assertFalse(self.user.email_verified)

    @override_settings(STATIC_URL="https://cdn.example.com/static/")
    def test_email_logo_supports_absolute_cdn_url(self):
        request = RequestFactory().get("/", secure=True)
        send_email_verification(request, self.user)
        self.assertEqual(EmailMarkup(mail.outbox[-1].alternatives[0].content).images[0]["src"],
                         "https://cdn.example.com/static/joatham_dashboard/img/email-logo.png")

    def test_resend_still_requires_post_pending_user_and_csrf(self):
        self.client.get(reverse("email_verification_resend"))
        Client().post(reverse("email_verification_resend"))
        guarded = Client(enforce_csrf_checks=True)
        session = guarded.session
        session["pending_verification_user_id"] = self.user.pk
        session.save()
        response = guarded.post(reverse("email_verification_resend"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_bilingual_confirmation_from_email_still_activates_once(self):
        for language in ("fr", "en"):
            with self.subTest(language=language), override(language):
                self.user.email_verified = False
                self.user.save(update_fields=["email_verified"])
                session = self.client.session
                session["pending_verification_user_id"] = self.user.pk
                session.save()
                self.select_language(language)
                self.client.post(reverse("email_verification_resend"), secure=True)
                url = EmailMarkup(mail.outbox[-1].alternatives[0].content).links[0]
                path = url.removeprefix("https://testserver")
                self.assertEqual(self.client.get(path, secure=True).status_code, 200)
                self.user.refresh_from_db()
                self.assertTrue(self.user.email_verified)
                self.assertEqual(self.client.get(path, secure=True).status_code, 400)
                self.assertNotIn("pending_verification_user_id", self.client.session)
