from io import BytesIO
from pathlib import Path
import tempfile

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.services.company_profile import build_entreprise_identity, build_logo_data_uri
from core.services.subscription import activate_subscription_for_entreprise, get_default_paid_plans
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement, Entreprise


class DashboardCompanyLogoTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        override = override_settings(MEDIA_ROOT=Path(temporary.name))
        override.enable()
        self.addCleanup(override.disable)
        self.companies = [create_entreprise("Société Àvenir"), create_entreprise("Entreprise B privée")]
        self.users = {}
        self.plan = Abonnement.objects.create(**next(p for p in get_default_paid_plans() if p["code"] == "premium"), actif=True)
        for index, company in enumerate(self.companies):
            content = BytesIO()
            Image.new("RGB", (120, 40), color=("teal" if index == 0 else "red")).save(content, format="PNG")
            company.logo.save(f"company-{index}.png", SimpleUploadedFile(f"company-{index}.png", content.getvalue()))
            for role in ("proprietaire", "gestionnaire", "comptable"):
                self.users[index, role] = create_user(f"logo-{index}-{role}", role, company)
            activate_subscription_for_entreprise(
                entreprise=company, plan=self.plan, utilisateur=self.users[index, "proprietaire"],
            )

    def request_dashboard(self, index, role, language="fr"):
        user = self.users[index, role]
        user.preferred_language = language
        user.save(update_fields=["preferred_language"])
        self.client.force_login(user)
        route = {"proprietaire": "proprietaire_dashboard", "gestionnaire": "gestion_dashboard", "comptable": "comptable_dashboard"}[role]
        return self.client.get(reverse(route), {"entreprise_id": self.companies[1 - index].pk})

    def test_each_role_only_renders_its_company_logo_in_fr_and_en(self):
        for language in ("fr", "en"):
            for index, company in enumerate(self.companies):
                for role in ("proprietaire", "gestionnaire", "comptable"):
                    with self.subTest(language=language, company=index, role=role):
                        response = self.request_dashboard(index, role, language)
                        self.assertEqual(response.status_code, 200)
                        identity = build_entreprise_identity(company)
                        self.assertEqual(response.context["entreprise_identity"]["logo_url"], identity["logo_url"])
                        self.assertContains(response, f'src="{identity["logo_url"]}"', count=1)
                        self.assertNotContains(response, self.companies[1 - index].logo.url)
                        self.assertContains(response, company.nom)
                        self.assertTemplateUsed(response, "joatham_dashboard/includes/company_heading.html")

    def test_no_logo_uses_initial_without_a_second_source(self):
        self.companies[0].logo = ""
        self.companies[0].save(update_fields=["logo"])
        for language in ("fr", "en"):
            for role in ("proprietaire", "gestionnaire", "comptable"):
                response = self.request_dashboard(0, role, language)
                self.assertNotContains(response, "data-company-logo")
                self.assertContains(response, 'class="dashboard-company-initial">S</span>')
                self.assertNotContains(response, self.companies[1].logo.url)

    def test_missing_storage_object_keeps_the_same_source_and_browser_fallback(self):
        self.companies[0].logo.storage.delete(self.companies[0].logo.name)
        response = self.request_dashboard(0, "proprietaire")
        self.assertContains(response, f'src="{self.companies[0].logo.url}"')
        self.assertContains(response, "dashboard-company-logo.js")
        self.assertContains(response, 'class="dashboard-company-initial">S</span>')

    def test_company_names_remain_original_and_html_escaped(self):
        self.companies[0].nom = "Àvenir <script>test</script>"
        self.companies[0].save(update_fields=["nom"])
        response = self.request_dashboard(0, "proprietaire", "en")
        self.assertContains(response, "Àvenir &lt;script&gt;test&lt;/script&gt;")
        self.assertNotContains(response, "<script>test</script>")
        self.companies[0].refresh_from_db()
        self.assertEqual(self.companies[0].nom, "Àvenir <script>test</script>")

    def test_anonymous_request_cannot_render_tenant_identity(self):
        response = self.client.get(reverse("proprietaire_dashboard"))
        self.assertEqual(response.status_code, 302)
        for company in self.companies:
            self.assertNotContains(response, company.logo.url, status_code=302)

    def test_reuses_the_existing_organisation_and_document_field(self):
        field = Entreprise._meta.get_field("logo")
        self.assertEqual(field.upload_to, "entreprises/logos/")
        company = self.companies[0]
        original = company.logo.name
        self.assertEqual(build_entreprise_identity(company)["logo_url"], company.logo.url)
        self.assertTrue(build_logo_data_uri(company).startswith("data:image/"))
        response = self.request_dashboard(0, "proprietaire")
        self.assertContains(response, company.logo.url)
        company.refresh_from_db()
        self.assertEqual(company.logo.name, original)
