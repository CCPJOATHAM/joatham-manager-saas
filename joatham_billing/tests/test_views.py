from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.services.subscription import start_trial_for_entreprise
from joatham_billing.models import Facture, Service
from joatham_products.models import Produit
from joatham_users.models import Abonnement

from .factories import create_client, create_entreprise, create_facture_sample, create_user


class BillingViewsPremiumTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Premium")
        self.user = create_user("owner-premium", "proprietaire", self.entreprise)
        self.plan = Abonnement.objects.create(
            nom="Premium",
            code="premium-billing",
            prix=49,
            duree_jours=30,
            actif=True,
        )
        start_trial_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.user)
        self.client_billing = create_client(self.entreprise, "Client Premium")
        self.service = Service.objects.create(
            entreprise=self.entreprise,
            nom="Audit express",
            prix=Decimal("125.00"),
            actif=True,
        )
        self.product = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Ordinateur portable",
            description="Ordinateur portable professionnel",
            reference="PC-01",
            prix_unitaire=Decimal("900.00"),
            quantite_stock=3,
            seuil_alerte=2,
            actif=True,
        )
        self.facture = create_facture_sample(self.entreprise, self.user, self.client_billing)
        self.client.force_login(self.user)

    def test_facture_list_displays_premium_sections(self):
        response = self.client.get(reverse("facture_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Facturation")
        self.assertContains(response, "Montant facture")
        self.assertContains(response, "Montant encaisse")
        self.assertContains(response, "Reste a encaisser")
        self.assertContains(response, self.facture.numero)

    def test_facture_detail_displays_redesigned_sections(self):
        response = self.client.get(reverse("facture_detail", args=[self.facture.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Prestations facturees")
        self.assertContains(response, "Enregistrer un paiement")
        self.assertContains(response, "Historique")
        self.assertContains(response, self.facture.numero)

    def test_facture_detail_displays_line_origin_badges(self):
        self.facture.statut = Facture.Statut.BROUILLON
        self.facture.paye = False
        self.facture.save(update_fields=["statut", "paye"])
        self.facture.lignes.all().delete()
        self.facture.lignes.create(
            produit=self.product,
            designation=self.product.description,
            quantite=1,
            prix_unitaire=self.product.prix_unitaire,
            tva=self.facture.tva,
        )
        self.facture.lignes.create(
            service=self.service,
            designation=self.service.nom,
            quantite=1,
            prix_unitaire=self.service.prix,
            tva=self.facture.tva,
        )
        self.facture.lignes.create(
            designation="Ligne libre speciale",
            quantite=1,
            prix_unitaire=Decimal("10.00"),
            tva=self.facture.tva,
        )

        response = self.client.get(reverse("facture_detail", args=[self.facture.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Produit")
        self.assertContains(response, "Service")
        self.assertContains(response, "Saisie libre")
        self.assertContains(response, self.product.nom)
        self.assertContains(response, self.service.nom)

    def test_facture_pdf_still_renders_successfully(self):
        response = self.client.get(reverse("facture_pdf", args=[self.facture.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_add_facture_form_exposes_service_selector_with_price_metadata(self):
        response = self.client.get(reverse("add_facture"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="service_id[]"')
        self.assertContains(response, 'name="product_id[]"')
        self.assertContains(response, 'data-prix="125')
        self.assertContains(response, self.service.nom)
        self.assertContains(response, self.product.nom)
        self.assertContains(response, 'data-stock="3"')

    def test_create_facture_uses_selected_service_when_label_and_price_are_blank(self):
        response = self.client.post(
            reverse("add_facture"),
            {
                "client": self.client_billing.id,
                "client_nom": "",
                "tva": "0",
                "remise": "0",
                "rabais": "0",
                "ristourne": "0",
                "service_id[]": [str(self.service.id)],
                "designation[]": [""],
                "quantite[]": ["2"],
                "prix[]": [""],
            },
        )

        self.assertEqual(response.status_code, 302)
        facture = Facture.objects.exclude(id=self.facture.id).latest("id")
        ligne = facture.lignes.get()
        self.assertEqual(ligne.designation, self.service.nom)
        self.assertEqual(ligne.prix_unitaire, self.service.prix)

    def test_edit_facture_uses_selected_service_and_allows_manual_price_override(self):
        self.facture.statut = Facture.Statut.BROUILLON
        self.facture.paye = False
        self.facture.save(update_fields=["statut", "paye"])

        response = self.client.post(
            reverse("edit_facture", args=[self.facture.id]),
            {
                "client": self.client_billing.id,
                "client_nom": "",
                "tva": "0",
                "remise": "0",
                "rabais": "0",
                "ristourne": "0",
                "service_id[]": [str(self.service.id)],
                "designation[]": [""],
                "quantite[]": ["3"],
                "prix[]": ["150.00"],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.facture.refresh_from_db()
        ligne = self.facture.lignes.get()
        self.assertEqual(ligne.designation, self.service.nom)
        self.assertEqual(ligne.prix_unitaire, Decimal("150.00"))

    def test_create_facture_uses_selected_product_when_manual_fields_are_blank(self):
        response = self.client.post(
            reverse("add_facture"),
            {
                "client": self.client_billing.id,
                "client_nom": "",
                "tva": "16",
                "remise": "0",
                "rabais": "0",
                "ristourne": "0",
                "product_id[]": [str(self.product.id)],
                "service_id[]": [""],
                "designation[]": [""],
                "quantite[]": ["2"],
                "prix[]": [""],
            },
        )

        self.assertEqual(response.status_code, 302)
        facture = Facture.objects.exclude(id=self.facture.id).latest("id")
        ligne = facture.lignes.get()
        self.assertEqual(ligne.produit_id, self.product.id)
        self.assertEqual(ligne.designation, self.product.description)
        self.assertEqual(ligne.prix_unitaire, self.product.prix_unitaire)
        self.assertEqual(ligne.tva, Decimal("16"))

    def test_create_facture_still_supports_manual_line_without_product_or_service(self):
        response = self.client.post(
            reverse("add_facture"),
            {
                "client": self.client_billing.id,
                "client_nom": "",
                "tva": "0",
                "remise": "0",
                "rabais": "0",
                "ristourne": "0",
                "product_id[]": [""],
                "service_id[]": [""],
                "designation[]": ["Ligne libre"],
                "quantite[]": ["1"],
                "prix[]": ["75.00"],
            },
        )

        self.assertEqual(response.status_code, 302)
        facture = Facture.objects.exclude(id=self.facture.id).latest("id")
        ligne = facture.lignes.get()
        self.assertIsNone(ligne.produit_id)
        self.assertEqual(ligne.designation, "Ligne libre")
        self.assertEqual(ligne.prix_unitaire, Decimal("75.00"))

    def test_comptable_sees_read_only_billing_actions_plus_payment(self):
        comptable = create_user("compta-premium", "comptable", self.entreprise)
        self.client.force_login(comptable)

        list_response = self.client.get(reverse("facture_list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, reverse("add_facture"))
        self.assertNotContains(list_response, "Modifier")
        self.assertContains(list_response, "Payer")

        detail_response = self.client.get(reverse("facture_detail", args=[self.facture.id]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertNotContains(detail_response, "Mettre a jour le statut")
        self.assertContains(detail_response, "Enregistrer un paiement")
