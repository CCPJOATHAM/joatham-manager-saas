from django.test import TestCase
from django.urls import reverse

from joatham_billing.tests.factories import create_entreprise, create_user


class CompanySettingsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Param")
        self.owner = create_user("owner-company", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("gestion-company", "gestionnaire", self.entreprise)

    def test_company_settings_is_owner_only(self):
        self.client.force_login(self.gestionnaire)
        forbidden = self.client.get(reverse("company_settings"))
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.owner)
        allowed = self.client.get(reverse("company_settings"))
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "Parametres entreprise")

    def test_owner_can_update_company_identity(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("company_settings"),
            {
                "nom": "Entreprise Renommee",
                "raison_sociale": "Enseigne Test",
                "adresse": "Avenue 1",
                "ville": "Matadi",
                "pays": "RDC",
                "devise": "USD",
                "telephone": "+243900000001",
                "email": "contact@test.cd",
                "banque": "Equity",
                "compte_bancaire": "123456",
                "rccm": "RCCM-1",
                "id_nat": "ID-1",
                "numero_impot": "IMP-1",
            },
        )
        self.assertRedirects(response, reverse("company_settings"))
        self.entreprise.refresh_from_db()
        self.assertEqual(self.entreprise.nom, "Entreprise Renommee")
        self.assertEqual(self.entreprise.banque, "Equity")
        self.assertEqual(self.entreprise.devise, "USD")
