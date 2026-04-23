from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.models import ActivityLog
from core.services.subscription import start_trial_for_entreprise
from joatham_products.models import Produit
from joatham_users.models import Abonnement

from .factories import create_entreprise, create_user
from ..exceptions import WorkflowFacturationError
from ..models import Facture, Service
from ..services.facturation import change_facture_status, create_facture, update_facture


class BillingServicesViewsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Services")
        self.autre_entreprise = create_entreprise("Entreprise Services B")
        self.owner = create_user("owner-services", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("manager-services", "gestionnaire", self.entreprise)
        self.comptable = create_user("accountant-services", "comptable", self.entreprise)
        self.owner_b = create_user("owner-services-b", "proprietaire", self.autre_entreprise)
        self.plan = Abonnement.objects.create(nom="Services", code="services", prix=10, duree_jours=30, actif=True)
        start_trial_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.owner)
        start_trial_for_entreprise(entreprise=self.autre_entreprise, plan=self.plan, utilisateur=self.owner_b)
        self.service = Service.objects.create(
            entreprise=self.entreprise,
            nom="Assistance bureautique",
            prix=Decimal("80.00"),
            actif=True,
        )

    def test_owner_can_create_service(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("service_create"),
            {"nom": "Formation Word", "prix": "120.00", "actif": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Service.objects.filter(entreprise=self.entreprise, nom="Formation Word").exists())
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="service_cree",
            ).exists()
        )

    def test_gestionnaire_can_update_service(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("service_update", args=[self.service.id]),
            {"nom": "Assistance avancée", "prix": "95.00", "actif": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.service.refresh_from_db()
        self.assertEqual(self.service.nom, "Assistance avancée")
        self.assertEqual(self.service.prix, Decimal("95.00"))

    def test_gestionnaire_can_toggle_service_status(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(reverse("service_toggle_status", args=[self.service.id]))
        self.assertEqual(response.status_code, 302)
        self.service.refresh_from_db()
        self.assertFalse(self.service.actif)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.gestionnaire,
                action="service_statut_modifie",
            ).exists()
        )

    def test_comptable_has_read_only_access(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("service_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Services")
        self.assertContains(response, "Lecture seule")
        self.assertNotContains(response, reverse("service_create"))

        create_response = self.client.get(reverse("service_create"))
        self.assertEqual(create_response.status_code, 403)

    def test_cross_tenant_update_is_blocked(self):
        external_service = Service.objects.create(
            entreprise=self.autre_entreprise,
            nom="Service externe",
            prix=Decimal("50.00"),
            actif=True,
        )
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("service_update", args=[external_service.id]))
        self.assertEqual(response.status_code, 404)


class BillingStockWorkflowTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Stock")
        self.autre_entreprise = create_entreprise("Entreprise Stock B")
        self.owner = create_user("owner-stock", "proprietaire", self.entreprise)
        self.owner_b = create_user("owner-stock-b", "proprietaire", self.autre_entreprise)
        self.plan = Abonnement.objects.create(nom="Stock", code="stock", prix=10, duree_jours=30, actif=True)
        start_trial_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.owner)
        start_trial_for_entreprise(entreprise=self.autre_entreprise, plan=self.plan, utilisateur=self.owner_b)
        self.product = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Routeur Wi-Fi",
            description="Routeur Wi-Fi double bande",
            reference="ROUTER-01",
            prix_unitaire=Decimal("50.00"),
            quantite_stock=2,
            seuil_alerte=5,
            actif=True,
        )
        self.service = Service.objects.create(
            entreprise=self.entreprise,
            nom="Installation reseau",
            prix=Decimal("35.00"),
            actif=True,
        )
        self.foreign_product = Produit.objects.create(
            entreprise=self.autre_entreprise,
            nom="Produit externe",
            description="Produit externe",
            reference="EXT-01",
            prix_unitaire=Decimal("20.00"),
            quantite_stock=10,
            seuil_alerte=1,
            actif=True,
        )

    def test_create_facture_rejects_quantity_above_available_stock(self):
        with self.assertRaises(WorkflowFacturationError) as context:
            create_facture(
                entreprise=self.entreprise,
                user=self.owner,
                tva=0,
                lignes=[
                    {
                        "product_id": str(self.product.id),
                        "designation": "",
                        "quantite": 5,
                        "prix": "",
                    }
                ],
            )

        self.product.refresh_from_db()
        self.assertIn("Stock insuffisant", str(context.exception))
        self.assertEqual(self.product.quantite_stock, 2)
        self.assertFalse(Facture.objects.filter(entreprise=self.entreprise).exists())

    def test_create_facture_decrements_stock_for_valid_product_line(self):
        facture = create_facture(
            entreprise=self.entreprise,
            user=self.owner,
            tva=0,
            lignes=[
                {
                    "product_id": str(self.product.id),
                    "designation": "",
                    "quantite": 2,
                    "prix": "",
                }
            ],
        )

        self.product.refresh_from_db()
        facture.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 0)
        self.assertTrue(facture.stock_applique)
        self.assertEqual(facture.statut, Facture.Statut.EMISE)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="stock_facture_decremente",
                objet_id=self.product.id,
            ).exists()
        )

    def test_update_brouillon_facture_revalidates_stock_without_double_decrement(self):
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom="Client test",
            tva=Decimal("0"),
            montant=Decimal("0"),
            description="",
        )
        facture.lignes.create(
            produit=self.product,
            designation=self.product.description,
            quantite=1,
            prix_unitaire=self.product.prix_unitaire,
            tva=Decimal("0"),
        )

        update_facture(
            facture=facture,
            user=self.owner,
            client_nom="Client test",
            tva=0,
            lignes=[
                {
                    "product_id": str(self.product.id),
                    "designation": "",
                    "quantite": 2,
                    "prix": "",
                }
            ],
        )
        self.product.refresh_from_db()
        facture.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 2)
        self.assertFalse(facture.stock_applique)
        self.assertEqual(facture.lignes.get().quantite, 2)

        change_facture_status(
            facture=facture,
            nouveau_statut=Facture.Statut.EMISE,
            user=self.owner,
            note="Validation manuelle du brouillon.",
        )

        self.product.refresh_from_db()
        facture.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 0)
        self.assertTrue(facture.stock_applique)

    def test_annulation_restores_product_stock(self):
        facture = create_facture(
            entreprise=self.entreprise,
            user=self.owner,
            tva=0,
            lignes=[
                {
                    "product_id": str(self.product.id),
                    "designation": "",
                    "quantite": 1,
                    "prix": "",
                }
            ],
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 1)

        change_facture_status(
            facture=facture,
            nouveau_statut=Facture.Statut.ANNULEE,
            user=self.owner,
            note="Annulation de recette.",
        )

        self.product.refresh_from_db()
        facture.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 2)
        self.assertFalse(facture.stock_applique)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="stock_facture_restaure",
                objet_id=self.product.id,
            ).exists()
        )

    def test_service_lines_do_not_change_stock(self):
        facture = create_facture(
            entreprise=self.entreprise,
            user=self.owner,
            tva=0,
            lignes=[
                {
                    "service_id": str(self.service.id),
                    "designation": "",
                    "quantite": 3,
                    "prix": "",
                }
            ],
        )

        self.product.refresh_from_db()
        facture.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 2)
        self.assertTrue(facture.stock_applique)
        self.assertFalse(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                action="stock_facture_decremente",
            ).exists()
        )

    def test_free_lines_do_not_change_stock(self):
        facture = create_facture(
            entreprise=self.entreprise,
            user=self.owner,
            tva=0,
            lignes=[
                {
                    "designation": "Prestation libre",
                    "quantite": 2,
                    "prix": "15.00",
                }
            ],
        )

        self.product.refresh_from_db()
        facture.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 2)
        self.assertTrue(facture.stock_applique)

    def test_cross_tenant_product_is_rejected_before_any_stock_movement(self):
        with self.assertRaises(WorkflowFacturationError):
            create_facture(
                entreprise=self.entreprise,
                user=self.owner,
                tva=0,
                lignes=[
                    {
                        "product_id": str(self.foreign_product.id),
                        "designation": "",
                        "quantite": 1,
                        "prix": "",
                    }
                ],
            )

        self.product.refresh_from_db()
        self.foreign_product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 2)
        self.assertEqual(self.foreign_product.quantite_stock, 10)
