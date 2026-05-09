from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.services.subscription import start_trial_for_entreprise
from joatham_users.models import Abonnement

from joatham_billing.models import Facture
from joatham_billing.tests.factories import create_entreprise, create_user

from .models import Produit, StockMovement
from .services.stock import apply_invoice_sale, apply_manual_entry


class StockMovementViewsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise UI Stock")
        self.autre_entreprise = create_entreprise("Entreprise UI Stock B")
        self.owner = create_user("owner-stock-ui", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("manager-stock-ui", "gestionnaire", self.entreprise)
        self.comptable = create_user("accountant-stock-ui", "comptable", self.entreprise)
        self.owner_b = create_user("owner-stock-ui-b", "proprietaire", self.autre_entreprise)
        self.plan = Abonnement.objects.create(nom="Produits Stock", code="products", prix=10, duree_jours=30, actif=True)
        start_trial_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.owner)
        start_trial_for_entreprise(entreprise=self.autre_entreprise, plan=self.plan, utilisateur=self.owner_b)

        self.product = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Switch reseau",
            description="Switch manageable",
            reference="SW-01",
            prix_unitaire=Decimal("120.00"),
            quantite_stock=10,
            seuil_alerte=2,
            actif=True,
        )
        self.product_b = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Point d'acces",
            description="Point d'acces Wi-Fi",
            reference="AP-01",
            prix_unitaire=Decimal("95.00"),
            quantite_stock=6,
            seuil_alerte=2,
            actif=True,
        )
        self.foreign_product = Produit.objects.create(
            entreprise=self.autre_entreprise,
            nom="Produit externe",
            description="Produit externe",
            reference="EXT-11",
            prix_unitaire=Decimal("50.00"),
            quantite_stock=7,
            seuil_alerte=1,
            actif=True,
        )

    def test_stock_movement_list_requires_stock_view_permission(self):
        response = self.client.get(reverse("stock_movement_list"))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.comptable)
        response = self.client.get(reverse("stock_movement_list"))
        self.assertEqual(response.status_code, 200)

    def test_stock_movement_list_is_scoped_to_entreprise(self):
        apply_manual_entry(
            entreprise=self.entreprise,
            produit=self.product,
            quantity=2,
            utilisateur=self.owner,
            reference="IN-A",
            reason="Entree A",
        )
        apply_manual_entry(
            entreprise=self.autre_entreprise,
            produit=self.foreign_product,
            quantity=1,
            utilisateur=self.owner_b,
            reference="IN-X",
            reason="Entree X",
        )

        self.client.force_login(self.comptable)
        response = self.client.get(reverse("stock_movement_list"))
        self.assertContains(response, "Switch reseau")
        self.assertNotContains(response, "Produit externe")

    def test_stock_movement_list_filters_by_product_type_and_source(self):
        first_movement = apply_manual_entry(
            entreprise=self.entreprise,
            produit=self.product,
            quantity=2,
            utilisateur=self.owner,
            reference="IN-A",
            reason="Entree A",
        )
        other_movement = apply_manual_entry(
            entreprise=self.entreprise,
            produit=self.product_b,
            quantity=1,
            utilisateur=self.owner,
            reference="IN-B",
            reason="Entree B",
        )
        facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom="Client",
            tva=Decimal("0"),
            montant=Decimal("0"),
            description="",
        )
        expected_movement = apply_invoice_sale(
            entreprise=self.entreprise,
            produit=self.product,
            quantity=1,
            facture=facture,
            utilisateur=self.owner,
        )

        self.client.force_login(self.comptable)
        response = self.client.get(
            reverse("stock_movement_list"),
            {
                "produit": str(self.product.id),
                "movement_type": StockMovement.MovementType.INVOICE_SALE,
                "source_app": "joatham_billing",
            },
        )
        self.assertContains(response, "Switch reseau")
        self.assertContains(response, "joatham_billing")
        movements = [row["instance"] for row in response.context["movements"]]
        self.assertEqual([movement.id for movement in movements], [expected_movement.id])
        self.assertNotIn(first_movement, movements)
        self.assertNotIn(other_movement, movements)

    def test_owner_can_create_manual_entry_via_view(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("stock_entry_create"),
            {
                "produit": str(self.product.id),
                "movement_type": StockMovement.MovementType.MANUAL_ENTRY,
                "quantity": "3",
                "reference": "ENT-UI",
                "reason": "Livraison",
                "comment": "Bon reception",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 13)
        self.assertTrue(
            StockMovement.objects.filter(
                entreprise=self.entreprise,
                produit=self.product,
                movement_type=StockMovement.MovementType.MANUAL_ENTRY,
                reference="ENT-UI",
            ).exists()
        )

    def test_gestionnaire_can_create_manual_exit_via_view(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("stock_exit_create"),
            {
                "produit": str(self.product.id),
                "movement_type": StockMovement.MovementType.MANUAL_EXIT,
                "quantity": "4",
                "reference": "OUT-UI",
                "reason": "Casse",
                "comment": "Sortie manuelle",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 6)
        self.assertTrue(
            StockMovement.objects.filter(
                entreprise=self.entreprise,
                produit=self.product,
                movement_type=StockMovement.MovementType.MANUAL_EXIT,
                reference="OUT-UI",
            ).exists()
        )

    def test_manual_exit_is_rejected_when_stock_is_insufficient(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("stock_exit_create"),
            {
                "produit": str(self.product.id),
                "movement_type": StockMovement.MovementType.MANUAL_EXIT,
                "quantity": "40",
                "reference": "OUT-KO",
                "reason": "Erreur",
                "comment": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 10)
        self.assertContains(response, "Stock insuffisant")

    def test_adjustment_view_handles_positive_and_negative_operations(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("stock_adjustment_create"),
            {
                "produit": str(self.product.id),
                "movement_type": StockMovement.MovementType.ADJUSTMENT_POSITIVE,
                "quantity": "2",
                "reference": "ADJ-P",
                "reason": "Correction positive",
                "comment": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 12)

        response = self.client.post(
            reverse("stock_adjustment_create"),
            {
                "produit": str(self.product.id),
                "movement_type": StockMovement.MovementType.ADJUSTMENT_NEGATIVE,
                "quantity": "3",
                "reference": "ADJ-N",
                "reason": "Correction negative",
                "comment": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 9)
        self.assertTrue(
            StockMovement.objects.filter(
                entreprise=self.entreprise,
                produit=self.product,
                movement_type=StockMovement.MovementType.ADJUSTMENT_NEGATIVE,
                reference="ADJ-N",
            ).exists()
        )

    def test_negative_adjustment_is_rejected_when_stock_is_insufficient(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("stock_adjustment_create"),
            {
                "produit": str(self.product.id),
                "movement_type": StockMovement.MovementType.ADJUSTMENT_NEGATIVE,
                "quantity": "99",
                "reference": "ADJ-KO",
                "reason": "Erreur",
                "comment": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stock insuffisant")
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 10)

    def test_cross_tenant_product_is_rejected_in_entry_form(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("stock_entry_create"),
            {
                "produit": str(self.foreign_product.id),
                "movement_type": StockMovement.MovementType.MANUAL_ENTRY,
                "quantity": "2",
                "reference": "ENT-X",
                "reason": "Cross tenant",
                "comment": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            StockMovement.objects.filter(
                entreprise=self.entreprise,
                produit_id=self.foreign_product.id,
            ).exists()
        )

    def test_comptable_can_view_but_cannot_create_stock_movements(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("stock_movement_list"))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse("stock_entry_create"))
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("stock_exit_create"))
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("stock_adjustment_create"))
        self.assertEqual(response.status_code, 403)
