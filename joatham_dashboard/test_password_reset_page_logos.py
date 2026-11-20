from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext, override

from joatham_billing.tests.factories import create_entreprise, create_user


class PasswordResetPageLogoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user("reset-logo", "proprietaire", create_entreprise("Société Àvenir"))

    def test_bilingual_request_and_confirm_pages_keep_fields_and_show_official_logo(self):
        for language in ("fr", "en"):
            with self.subTest(language=language), override(language):
                response = self.client.post(reverse("set_language"), {
                    "language": language, "next": reverse("password_reset"),
                })
                self.assertEqual(response.status_code, 302)
                request_page = self.client.get(reverse("password_reset"))
                token = default_token_generator.make_token(self.user)
                confirm = self.client.get(reverse("password_reset_confirm", kwargs={
                    "uidb64": urlsafe_base64_encode(force_bytes(self.user.pk)), "token": token,
                }), follow=True)
                for response, title, fields in (
                    (request_page, gettext("Réinitialisez votre mot de passe"), ("email",)),
                    (confirm, gettext("Définissez un nouveau mot de passe"), ("new_password1", "new_password2")),
                ):
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, f'<html lang="{language}">')
                    self.assertContains(response, title)
                    self.assertContains(response, 'class="brand-logo" src="/static/joatham_dashboard/img/login-logo.webp" alt="JOATHAM Manager"')
                    self.assertNotContains(response, '<div class="brand">JOATHAM Manager</div>')
                    self.assertContains(response, 'name="csrfmiddlewaretoken"')
                    self.assertEqual(tuple(response.context["form"].fields), fields)
                self.assertTrue(confirm.context["validlink"])

    def test_invalid_link_keeps_bilingual_recovery_action_and_logo(self):
        for language in ("fr", "en"):
            with self.subTest(language=language), override(language):
                self.client.post(reverse("set_language"), {"language": language, "next": reverse("password_reset")})
                response = self.client.get(reverse("password_reset_confirm", kwargs={
                    "uidb64": urlsafe_base64_encode(force_bytes(self.user.pk)), "token": "invalid-token",
                }))
                self.assertFalse(response.context["validlink"])
                self.assertContains(response, gettext("Lien invalide ou expiré"))
                self.assertContains(response, f'href="{reverse("password_reset")}"')
                self.assertContains(response, 'alt="JOATHAM Manager"')
