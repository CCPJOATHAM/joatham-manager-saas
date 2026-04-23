from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.models import ActivityLog
from core.services.subscription import start_trial_for_entreprise
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement

from .models import Produit
from .selectors.products import (
    STOCK_FILTER_LOW,
    STOCK_FILTER_RUPTURE,
    get_product_counts_by_entreprise,
    get_products_by_entreprise,
)
from .services.products_service import create_product_for_entreprise, update_product_for_entreprise


class ProductSelectorsTests(TestCase):
    def setUp(self):
        self.entreprise_a = create_entreprise("Entreprise Produits A")
        self.entreprise_b = create_entreprise("Entreprise Produits B")
        self.produit_ok = Produit.objects.create(
            entreprise=self.entreprise_a,
            nom="Ordinateur",
            reference="PRD-001",
            prix_unitaire=Decimal("1000.00"),
            quantite_stock=10,
            seuil_alerte=2,
        )
        self.produit_low = Produit.objects.create(
            entreprise=self.entreprise_a,
            nom="Imprimante",
            reference="PRD-002",
            prix_unitaire=Decimal("250.00"),
            quantite_stock=2,
            seuil_alerte=3,
        )
        self.produit_out = Produit.objects.create(
            entreprise=self.entreprise_a,
            nom="Routeur",
            reference="PRD-003",
            prix_unitaire=Decimal("80.00"),
            quantite_stock=0,
            seuil_alerte=1,
        )
        Produit.objects.create(
            entreprise=self.entreprise_b,
            nom="Produit Externe",
            reference="PRD-X",
            prix_unitaire=Decimal("99.00"),
            quantite_stock=5,
            seuil_alerte=1,
        )

    def test_products_are_scoped_to_entreprise(self):
        products = list(get_products_by_entreprise(self.entreprise_a))
        self.assertEqual([product.id for product in products], [self.produit_low.id, self.produit_ok.id, self.produit_out.id])

    def test_products_can_be_filtered_by_stock_state(self):
        low_products = list(get_products_by_entreprise(self.entreprise_a, stock_filter=STOCK_FILTER_LOW))
        rupture_products = list(get_products_by_entreprise(self.entreprise_a, stock_filter=STOCK_FILTER_RUPTURE))

        self.assertEqual({product.id for product in low_products}, {self.produit_low.id, self.produit_out.id})
        self.assertEqual([product.id for product in rupture_products], [self.produit_out.id])

    def test_product_counts_are_computed_per_entreprise(self):
        counts = get_product_counts_by_entreprise(self.entreprise_a)
        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["stock_faible"], 2)
        self.assertEqual(counts["rupture"], 1)
        self.assertEqual(counts["actifs"], 3)


class ProductServicesTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Produits Services")
        self.owner = create_user("owner-products", "proprietaire", self.entreprise)

    def test_create_product_creates_audit_event(self):
        produit = create_product_for_entreprise(
            entreprise=self.entreprise,
            nom="Scanner",
            description="Scanner reseau haute definition",
            reference="SCN-1",
            prix_unitaire=Decimal("150.00"),
            quantite_stock=5,
            seuil_alerte=2,
            actif=True,
            utilisateur=self.owner,
        )

        self.assertEqual(produit.entreprise, self.entreprise)
        self.assertEqual(produit.description, "Scanner reseau haute definition")
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="produit_cree",
                objet_id=produit.id,
            ).exists()
        )

    def test_update_product_logs_modification_and_stock_change(self):
        produit = create_product_for_entreprise(
            entreprise=self.entreprise,
            nom="Clavier",
            description="Clavier bureautique",
            reference="KB-1",
            prix_unitaire=Decimal("20.00"),
            quantite_stock=8,
            seuil_alerte=3,
            actif=True,
            utilisateur=self.owner,
        )

        update_product_for_entreprise(
            entreprise=self.entreprise,
            product_id=produit.id,
            nom="Clavier sans fil",
            description="Clavier sans fil rechargeable",
            reference="KB-1",
            prix_unitaire=Decimal("25.00"),
            quantite_stock=2,
            seuil_alerte=3,
            actif=True,
            utilisateur=self.owner,
        )

        produit.refresh_from_db()
        self.assertEqual(produit.nom, "Clavier sans fil")
        self.assertEqual(produit.description, "Clavier sans fil rechargeable")
        self.assertEqual(produit.quantite_stock, 2)
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="produit_modifie",
                objet_id=produit.id,
            ).exists()
        )
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="stock_modifie",
                objet_id=produit.id,
            ).exists()
        )


class ProductViewsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Produits Vue")
        self.autre_entreprise = create_entreprise("Entreprise Produits Vue B")
        self.owner = create_user("owner-products-view", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("manager-products-view", "gestionnaire", self.entreprise)
        self.comptable = create_user("accountant-products-view", "comptable", self.entreprise)
        self.other_owner = create_user("owner-products-other", "proprietaire", self.autre_entreprise)
        self.plan = Abonnement.objects.create(nom="Produits", code="products", prix=10, duree_jours=30, actif=True)
        start_trial_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.owner)
        start_trial_for_entreprise(entreprise=self.autre_entreprise, plan=self.plan, utilisateur=self.other_owner)
        self.produit = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Tablette",
            reference="TAB-01",
            prix_unitaire=Decimal("300.00"),
            quantite_stock=1,
            seuil_alerte=2,
        )

    def test_owner_can_create_product(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("product_create"),
            {
                "nom": "Projecteur",
                "reference": "PRJ-1",
                "prix_unitaire": "450.00",
                "quantite_stock": "4",
                "seuil_alerte": "1",
                "actif": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Produit.objects.filter(entreprise=self.entreprise, nom="Projecteur").exists())

    def test_gestionnaire_can_update_product(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("product_update", args=[self.produit.id]),
            {
                "nom": "Tablette Pro",
                "reference": "TAB-01",
                "prix_unitaire": "320.00",
                "quantite_stock": "0",
                "seuil_alerte": "2",
                "actif": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.nom, "Tablette Pro")
        self.assertEqual(self.produit.stock_status, "rupture")

    def test_comptable_has_read_only_access(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("product_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Produits")
        self.assertContains(response, "Lecture seule")
        self.assertNotContains(response, reverse("product_create"))

        create_response = self.client.get(reverse("product_create"))
        self.assertEqual(create_response.status_code, 403)

    def test_product_list_filters_work(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("product_list"), {"stock": "rupture"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucun produit trouvé")

        self.produit.quantite_stock = 0
        self.produit.save(update_fields=["quantite_stock"])
        response = self.client.get(reverse("product_list"), {"stock": "rupture"})
        self.assertContains(response, "Tablette")

    def test_cross_tenant_update_is_blocked(self):
        external_product = Produit.objects.create(
            entreprise=self.autre_entreprise,
            nom="Produit Externe",
            reference="EXT-1",
            prix_unitaire=Decimal("10.00"),
            quantite_stock=5,
            seuil_alerte=1,
        )
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("product_update", args=[external_product.id]))
        self.assertEqual(response.status_code, 404)
