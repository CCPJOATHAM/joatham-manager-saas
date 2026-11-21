"""Public layout contracts; pricing and signup behavior remain in PublicHomeTests."""
from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse
from django.conf import settings
from core.services.language import LANGUAGE_SESSION_KEY


class PageElements(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.elements = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class PublicHomePresentationTests(TestCase):
    def test_both_public_routes_keep_official_logos_and_post_language_fallback(self):
        for language, apply_label, menu_label in (
            ("fr", "Appliquer la langue", "Afficher ou masquer la navigation"),
            ("en", "Apply language", "Show or hide navigation"),
        ):
            self.client.post(reverse("set_language"), {"language": language, "next": reverse("public_home")})
            for route in ("public_home", "public_discover"):
                with self.subTest(language=language, route=route):
                    response = self.client.get(reverse(route), {"campaign": "demo"})
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, apply_label)
                    self.assertContains(response, menu_label)
                    self.assertNotContains(response, '>Changer</button>')
                    elements = PageElements(response.content.decode()).elements
                    logos = [attrs for tag, attrs in elements if tag == "img" and attrs.get("class") == "brand-logo"]
                    self.assertEqual(len(logos), 2)
                    self.assertTrue(all(attrs["src"].endswith("joatham_dashboard/img/login-logo.webp") for attrs in logos))
                    self.assertTrue(all(attrs["alt"] == "JOATHAM Manager" for attrs in logos))
                    form = next(attrs for tag, attrs in elements if tag == "form" and "data-public-language" in attrs)
                    self.assertEqual(form["method"], "post")
                    self.assertEqual(form["action"], reverse("set_language"))
                    self.assertIn(("input", {"type": "hidden", "name": "next", "value": reverse(route) + "?campaign=demo"}), elements)
                    self.assertTrue(any(tag == "input" and attrs.get("name") == "csrfmiddlewaretoken" for tag, attrs in elements))
                    self.assertEqual([attrs["value"] for tag, attrs in elements if tag == "option"], ["fr", "en"])
                    for anchor in ("accueil", "fonctionnalites", "tarifs", "apropos", "contact"):
                        self.assertTrue(any(attrs.get("id") == anchor for tag, attrs in elements))
                        self.assertTrue(any(tag == "a" and attrs.get("href") == "#" + anchor for tag, attrs in elements))
                    # No hardcoded HTML hidden state: all navigation survives disabled JavaScript.
                    nav = next(attrs for tag, attrs in elements if attrs.get("id") == "public-navigation")
                    self.assertNotIn("hidden", nav)

    def test_language_switch_round_trip_keeps_public_route_and_pricing_links(self):
        destination = reverse("public_discover") + "?campaign=demo#tarifs"
        for language, monthly, annual in (("en", "10 USD/month", "96 USD/year"), ("fr", "10 USD/mois", "96 USD/an")):
            with self.subTest(language=language):
                response = self.client.post(reverse("set_language"), {"language": language, "next": destination})
                self.assertEqual(response["Location"], destination)
                self.assertEqual(self.client.session[LANGUAGE_SESSION_KEY], language)
                self.assertEqual(self.client.cookies[settings.LANGUAGE_COOKIE_NAME].value, language)
                page = self.client.get(reverse("public_discover"))
                self.assertContains(page, monthly)
                self.assertContains(page, annual)
                for code in ("free", "starter", "pro", "premium"):
                    self.assertContains(page, f'data-signup-yearly-url="{reverse("signup")}?plan={code}&amp;billing=yearly"')
                    self.assertContains(page, f'{reverse("signup")}?plan={code}&amp;billing=monthly')
