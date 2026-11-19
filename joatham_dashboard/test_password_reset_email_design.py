import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from unittest.mock import patch

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.translation import gettext, override

from joatham_billing.tests.factories import create_entreprise, create_user


class EmailLinks(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.links = []
        self.images = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.links.append(attrs["href"])
        if tag == "img":
            self.images.append(attrs)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetEmailDesignTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user("reset-design", "proprietaire", create_entreprise("Société Àvenir"))
        self.user.email = "reset-design@example.com"
        self.user.save(update_fields=["email"])

    def request_email(self, language):
        cache.clear()
        self.client.post(reverse("set_language"), {"language": language, "next": reverse("password_reset")})
        response = self.client.post(reverse("password_reset"), {"email": self.user.email}, secure=True)
        self.assertRedirects(response, reverse("password_reset_done"))
        return mail.outbox[-1]

    def test_bilingual_multipart_email_preserves_subject_text_links_and_security(self):
        for language in ("fr", "en"):
            with self.subTest(language=language), override(language):
                email = self.request_email(language)
                self.assertEqual(email.subject, gettext("Réinitialisation de votre mot de passe | JOATHAM Manager"))
                self.assertEqual(email.to, [self.user.email])
                self.assertEqual(email.alternatives[0].mimetype, "text/html")
                html = email.alternatives[0].content
                url = re.search(r"https://testserver/reset/\S+", email.body).group(0)
                self.assertEqual(EmailLinks(html).links, [url, url])
                self.assertContainsHtmlLanguage(html, language)
                self.assertIn(gettext("Définir un nouveau mot de passe"), html)
                security = gettext("Si vous n’êtes pas à l’origine de cette demande, ignorez simplement cet email. Votre mot de passe actuel restera inchangé.")
                self.assertIn(security, html)
                self.assertIn(security, email.body)
                self.assertIn(gettext("Ce lien est temporaire et ne peut être utilisé qu’une seule fois."), email.body)
                image = EmailLinks(html).images[0]
                self.assertEqual(image["src"], "https://testserver/static/joatham_dashboard/img/email-logo.png")
                self.assertEqual(image["alt"], "JOATHAM Manager")
                self.assertNotIn("<html", email.body)
                self.assertNotIn("<img", email.body)
                parts = list(email.message().iter_parts())
                self.assertEqual([part.get_content_type() for part in parts], ["text/plain", "text/html"])

    def assertContainsHtmlLanguage(self, html, language):
        self.assertIn(f'<html lang="{language}">', html)

    def test_bilingual_button_token_changes_password_once(self):
        for language in ("fr", "en"):
            with self.subTest(language=language):
                email = self.request_email(language)
                url = EmailLinks(email.alternatives[0].content).links[0]
                path = url.removeprefix("https://testserver")
                token = path.rstrip("/").split("/")[-1]
                self.user.refresh_from_db()
                self.assertTrue(default_token_generator.check_token(self.user, token))
                confirm = self.client.get(path, secure=True)
                response = self.client.post(confirm.url, {
                    "new_password1": "NouveauMotDePasse987!" + language,
                    "new_password2": "NouveauMotDePasse987!" + language,
                }, secure=True)
                self.assertRedirects(response, reverse("password_reset_complete"))
                self.user.refresh_from_db()
                self.assertTrue(self.user.check_password("NouveauMotDePasse987!" + language))
                self.assertFalse(default_token_generator.check_token(self.user, token))
                self.assertFalse(self.client.get(path, secure=True).context["validlink"])

    @override_settings(PASSWORD_RESET_TIMEOUT=60)
    def test_bilingual_email_token_still_expires(self):
        now = datetime(2026, 11, 19, 12)
        for language in ("fr", "en"):
            with self.subTest(language=language):
                with patch.object(default_token_generator, "_now", return_value=now):
                    email = self.request_email(language)
                token = EmailLinks(email.alternatives[0].content).links[0].rstrip("/").split("/")[-1]
                with patch.object(default_token_generator, "_now", return_value=now + timedelta(seconds=61)):
                    self.assertFalse(default_token_generator.check_token(self.user, token))

    def test_absolute_static_url_is_not_prefixed_with_reset_domain(self):
        context = {"protocol": "https", "domain": "app.example.com", "uid": "MQ", "token": "preview-only"}
        for language in ("fr", "en"):
            with self.subTest(language=language), override(language), override_settings(STATIC_URL="https://cdn.example.com/assets/"):
                html = render_to_string("joatham_dashboard/emails/password_reset_email.html", context)
                self.assertEqual(EmailLinks(html).images[0]["src"], "https://cdn.example.com/assets/joatham_dashboard/img/email-logo.png")
