from decimal import Decimal

from django.test import TestCase

from core.models import ActivityLog
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.permissions import PERMISSIONS, ROLE_COMPTABLE, ROLE_GESTIONNAIRE, ROLE_PROPRIETAIRE

from .models import Produit, StockMovement
from .selectors.stock import (
    get_recent_stock_movements,
    get_stock_movements_for_entreprise,
    get_stock_movements_for_product,
)
from .services.stock import (
    StockOperationError,
    apply_adjustment,
    apply_invoice_sale,
    apply_manual_entry,
    apply_manual_exit,
    restore_invoice_stock,
)


class StockMovementServiceTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Stock Services")
        self.autre_entreprise = create_entreprise("Entreprise Stock Externe")
        self.owner = create_user("owner-stock-services", "proprietaire", self.entreprise)
        self.produit = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Ordinateur portable",
            reference="STK-001",
            prix_unitaire=Decimal("900.00"),
            quantite_stock=10,
            seuil_alerte=2,
        )
        self.produit_externe = Produit.objects.create(
            entreprise=self.autre_entreprise,
            nom="Produit externe",
            reference="STK-X",
            prix_unitaire=Decimal("120.00"),
            quantite_stock=5,
            seuil_alerte=1,
        )

    def test_manual_entry_creates_movement_and_updates_product_stock(self):
        movement = apply_manual_entry(
            entreprise=self.entreprise,
            produit=self.produit,
            quantity=4,
            utilisateur=self.owner,
            unit_cost=Decimal("875.00"),
            reference="ENT-1",
            reason="Reapprovisionnement",
        )

        self.produit.refresh_from_db()
        self.assertEqual(self.produit.quantite_stock, 14)
        self.assertEqual(movement.movement_type, StockMovement.MovementType.MANUAL_ENTRY)
        self.assertEqual(movement.quantity, 4)
        self.assertEqual(movement.stock_before, 10)
        self.assertEqual(movement.stock_after, 14)
        self.assertEqual(movement.reference, "ENT-1")
        self.assertTrue(
            ActivityLog.objects.filter(
                entreprise=self.entreprise,
                utilisateur=self.owner,
                action="stock_movement_recorded",
                objet_id=movement.id,
            ).exists()
        )

    def test_manual_exit_creates_movement_and_updates_product_stock(self):
        movement = apply_manual_exit(
            entreprise=self.entreprise,
            produit=self.produit,
            quantity=3,
            utilisateur=self.owner,
            reference="SORT-1",
            reason="Perte controlee",
        )

        self.produit.refresh_from_db()
        self.assertEqual(self.produit.quantite_stock, 7)
        self.assertEqual(movement.movement_type, StockMovement.MovementType.MANUAL_EXIT)
        self.assertEqual(movement.stock_before, 10)
        self.assertEqual(movement.stock_after, 7)

    def test_manual_exit_is_blocked_when_stock_is_insufficient(self):
        with self.assertRaises(StockOperationError):
            apply_manual_exit(
                entreprise=self.entreprise,
                produit=self.produit,
                quantity=11,
                utilisateur=self.owner,
            )

        self.produit.refresh_from_db()
        self.assertEqual(self.produit.quantite_stock, 10)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_non_positive_quantities_are_rejected(self):
        for invalid_quantity in (0, -2):
            with self.subTest(quantity=invalid_quantity):
                with self.assertRaises(StockOperationError):
                    apply_manual_entry(
                        entreprise=self.entreprise,
                        produit=self.produit,
                        quantity=invalid_quantity,
                        utilisateur=self.owner,
                    )

    def test_cross_tenant_product_is_rejected(self):
        with self.assertRaises(StockOperationError):
            apply_manual_entry(
                entreprise=self.entreprise,
                produit=self.produit_externe,
                quantity=2,
                utilisateur=self.owner,
            )

    def test_adjustments_and_invoice_operations_keep_stock_synced(self):
        positive = apply_adjustment(
            entreprise=self.entreprise,
            produit=self.produit,
            quantity=2,
            movement_type=StockMovement.MovementType.ADJUSTMENT_POSITIVE,
            utilisateur=self.owner,
            reason="Correction inventaire",
        )
        negative = apply_adjustment(
            entreprise=self.entreprise,
            produit=self.produit,
            quantity=5,
            movement_type=StockMovement.MovementType.ADJUSTMENT_NEGATIVE,
            utilisateur=self.owner,
            reason="Casse",
        )
        sale = apply_invoice_sale(
            entreprise=self.entreprise,
            produit=self.produit,
            quantity=3,
            utilisateur=self.owner,
            reference="F-0001",
            source_app="joatham_billing",
            source_model="Facture",
            source_id=100,
        )
        restore = restore_invoice_stock(
            entreprise=self.entreprise,
            produit=self.produit,
            quantity=3,
            utilisateur=self.owner,
            reference="F-0001",
            source_app="joatham_billing",
            source_model="Facture",
            source_id=100,
        )

        self.produit.refresh_from_db()
        self.assertEqual(self.produit.quantite_stock, 7)
        self.assertEqual((positive.stock_before, positive.stock_after), (10, 12))
        self.assertEqual((negative.stock_before, negative.stock_after), (12, 7))
        self.assertEqual((sale.stock_before, sale.stock_after), (7, 4))
        self.assertEqual((restore.stock_before, restore.stock_after), (4, 7))


class StockMovementSelectorsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Stock Selectors")
        self.autre_entreprise = create_entreprise("Entreprise Stock Selectors Externe")
        self.owner = create_user("owner-stock-selectors", "proprietaire", self.entreprise)
        self.autre_owner = create_user("owner-stock-selectors-other", "proprietaire", self.autre_entreprise)
        self.produit_a = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Produit A",
            reference="SEL-A",
            prix_unitaire=Decimal("50.00"),
            quantite_stock=20,
            seuil_alerte=2,
        )
        self.produit_b = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Produit B",
            reference="SEL-B",
            prix_unitaire=Decimal("80.00"),
            quantite_stock=12,
            seuil_alerte=2,
        )
        self.produit_externe = Produit.objects.create(
            entreprise=self.autre_entreprise,
            nom="Produit X",
            reference="SEL-X",
            prix_unitaire=Decimal("40.00"),
            quantite_stock=15,
            seuil_alerte=1,
        )

        self.entry_a = apply_manual_entry(
            entreprise=self.entreprise,
            produit=self.produit_a,
            quantity=3,
            utilisateur=self.owner,
            reference="ENTRY-A",
        )
        self.exit_a = apply_manual_exit(
            entreprise=self.entreprise,
            produit=self.produit_a,
            quantity=4,
            utilisateur=self.owner,
            reference="EXIT-A",
        )
        self.adjust_b = apply_adjustment(
            entreprise=self.entreprise,
            produit=self.produit_b,
            quantity=2,
            movement_type=StockMovement.MovementType.ADJUSTMENT_POSITIVE,
            utilisateur=self.owner,
            reference="ADJ-B",
        )
        apply_manual_entry(
            entreprise=self.autre_entreprise,
            produit=self.produit_externe,
            quantity=1,
            utilisateur=self.autre_owner,
            reference="ENTRY-X",
        )

    def test_selectors_are_scoped_to_entreprise(self):
        movements = list(get_stock_movements_for_entreprise(self.entreprise))
        self.assertEqual({movement.id for movement in movements}, {self.entry_a.id, self.exit_a.id, self.adjust_b.id})

    def test_selector_can_filter_by_product(self):
        movements = list(get_stock_movements_for_product(self.entreprise, self.produit_a))
        self.assertEqual({movement.id for movement in movements}, {self.entry_a.id, self.exit_a.id})

    def test_selector_can_filter_by_type(self):
        movements = list(
            get_stock_movements_for_entreprise(
                self.entreprise,
                movement_type=StockMovement.MovementType.MANUAL_ENTRY,
            )
        )
        self.assertEqual([movement.id for movement in movements], [self.entry_a.id])

    def test_recent_selector_respects_limit(self):
        movements = list(get_recent_stock_movements(self.entreprise, limit=2))
        self.assertEqual(len(movements), 2)


class StockPermissionsTests(TestCase):
    def test_stock_permissions_are_registered_in_matrix(self):
        self.assertEqual(PERMISSIONS["stock.view"], {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE})
        self.assertEqual(PERMISSIONS["stock.move"], {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE})
        self.assertEqual(PERMISSIONS["stock.adjust"], {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE})
        self.assertEqual(PERMISSIONS["stock.inventory"], {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE})
        self.assertEqual(PERMISSIONS["stock.export"], {ROLE_PROPRIETAIRE, ROLE_COMPTABLE})
