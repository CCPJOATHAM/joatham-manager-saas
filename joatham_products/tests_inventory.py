import warnings
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.services.subscription import activate_subscription_for_entreprise
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement

from .models import InventoryLine, InventorySession, Produit, StockMovement
from .selectors.inventory import get_inventory_sessions_for_entreprise
from .services.inventory import (
    InventoryOperationError,
    cancel_inventory_session,
    close_inventory_session,
    create_inventory_session,
    record_inventory_count,
    start_inventory_session,
    validate_inventory_session,
)


class InventoryModelsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Inventaire Modeles")
        self.owner = create_user("owner-inventory-models", "proprietaire", self.entreprise)
        self.product = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Routeur",
            reference="INV-M-1",
            prix_unitaire=Decimal("40.00"),
            quantite_stock=8,
            seuil_alerte=1,
        )

    def test_inventory_session_and_line_can_be_created(self):
        session = InventorySession.objects.create(
            entreprise=self.entreprise,
            name="Inventaire test",
            created_by=self.owner,
        )
        line = InventoryLine.objects.create(
            session=session,
            entreprise=self.entreprise,
            produit=self.product,
            theoretical_quantity=8,
            counted_quantity=None,
            difference=0,
        )
        self.assertEqual(session.status, InventorySession.Status.DRAFT)
        self.assertIsNone(line.counted_quantity)
        self.assertEqual(line.difference, 0)

    def test_inventory_line_is_unique_per_session_and_product(self):
        session = InventorySession.objects.create(
            entreprise=self.entreprise,
            name="Inventaire unique",
            created_by=self.owner,
        )
        InventoryLine.objects.create(
            session=session,
            entreprise=self.entreprise,
            produit=self.product,
            theoretical_quantity=8,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InventoryLine.objects.create(
                    session=session,
                    entreprise=self.entreprise,
                    produit=self.product,
                    theoretical_quantity=8,
                )

    def test_inventory_line_saves_difference(self):
        session = InventorySession.objects.create(
            entreprise=self.entreprise,
            name="Inventaire diff",
            created_by=self.owner,
        )
        line = InventoryLine.objects.create(
            session=session,
            entreprise=self.entreprise,
            produit=self.product,
            theoretical_quantity=8,
            counted_quantity=11,
        )
        self.assertEqual(line.difference, 3)


class InventoryServicesTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Inventaire Services")
        self.autre_entreprise = create_entreprise("Entreprise Inventaire Externe")
        self.owner = create_user("owner-inventory-services", "proprietaire", self.entreprise)
        self.owner_b = create_user("owner-inventory-services-b", "proprietaire", self.autre_entreprise)
        self.product_a = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Switch",
            reference="INV-S-1",
            prix_unitaire=Decimal("100.00"),
            quantite_stock=10,
            seuil_alerte=2,
            actif=True,
        )
        self.product_b = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Borne Wi-Fi",
            reference="INV-S-2",
            prix_unitaire=Decimal("80.00"),
            quantite_stock=5,
            seuil_alerte=1,
            actif=True,
        )
        self.product_inactive = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Produit inactif",
            reference="INV-S-3",
            prix_unitaire=Decimal("20.00"),
            quantite_stock=4,
            seuil_alerte=1,
            actif=False,
        )
        self.product_external = Produit.objects.create(
            entreprise=self.autre_entreprise,
            nom="Externe",
            reference="INV-X-1",
            prix_unitaire=Decimal("22.00"),
            quantite_stock=9,
            seuil_alerte=1,
            actif=True,
        )

    def test_create_inventory_session_with_active_products_freezes_theoretical_stock(self):
        session = create_inventory_session(
            entreprise=self.entreprise,
            name="Inventaire mensuel",
            comment="Mai",
            utilisateur=self.owner,
            include_active_products=True,
        )
        lines = list(session.lines.order_by("produit__nom"))
        self.assertEqual(session.status, InventorySession.Status.DRAFT)
        self.assertEqual({line.produit_id for line in lines}, {self.product_a.id, self.product_b.id})
        self.assertEqual(lines[0].counted_quantity, None)

        line_a = session.lines.get(produit=self.product_a)
        self.product_a.quantite_stock = 15
        self.product_a.save(update_fields=["quantite_stock"])
        line_a.refresh_from_db()
        self.assertEqual(line_a.theoretical_quantity, 10)

    def test_record_inventory_count_updates_difference(self):
        session = create_inventory_session(
            entreprise=self.entreprise,
            name="Inventaire comptage",
            utilisateur=self.owner,
        )
        session = session.__class__.objects.get(pk=session.pk)

        start_inventory_session(entreprise=self.entreprise, session_id=session.id)
        line = session.lines.get(produit=self.product_a)
        line = record_inventory_count(
            entreprise=self.entreprise,
            session_id=session.id,
            line_id=line.id,
            counted_quantity=7,
            comment="Comptage corrige",
        )
        self.assertEqual(line.counted_quantity, 7)
        self.assertEqual(line.difference, -3)

    def test_validate_inventory_with_positive_difference_creates_positive_adjustment(self):
        session = create_inventory_session(entreprise=self.entreprise, name="Inventaire +", utilisateur=self.owner)

        start_inventory_session(entreprise=self.entreprise, session_id=session.id)
        line = session.lines.get(produit=self.product_a)
        record_inventory_count(entreprise=self.entreprise, session_id=session.id, line_id=line.id, counted_quantity=13, comment="")
        other_line = session.lines.get(produit=self.product_b)
        record_inventory_count(entreprise=self.entreprise, session_id=session.id, line_id=other_line.id, counted_quantity=5, comment="")
        close_inventory_session(entreprise=self.entreprise, session_id=session.id)

        validate_inventory_session(entreprise=self.entreprise, session_id=session.id, utilisateur=self.owner)

        self.product_a.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(session.status, InventorySession.Status.VALIDATED)
        self.assertEqual(self.product_a.quantite_stock, 13)
        movement = StockMovement.objects.get(
            entreprise=self.entreprise,
            produit=self.product_a,
            movement_type=StockMovement.MovementType.ADJUSTMENT_POSITIVE,
            source_model="InventoryLine",
            source_id=line.id,
        )
        self.assertEqual(movement.reference, f"INV-{session.id}")

    def test_validate_inventory_with_negative_difference_creates_negative_adjustment(self):
        session = create_inventory_session(entreprise=self.entreprise, name="Inventaire -", utilisateur=self.owner)

        start_inventory_session(entreprise=self.entreprise, session_id=session.id)
        line = session.lines.get(produit=self.product_a)
        record_inventory_count(entreprise=self.entreprise, session_id=session.id, line_id=line.id, counted_quantity=6, comment="")
        other_line = session.lines.get(produit=self.product_b)
        record_inventory_count(entreprise=self.entreprise, session_id=session.id, line_id=other_line.id, counted_quantity=5, comment="")
        close_inventory_session(entreprise=self.entreprise, session_id=session.id)

        validate_inventory_session(entreprise=self.entreprise, session_id=session.id, utilisateur=self.owner)

        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.quantite_stock, 6)
        self.assertTrue(
            StockMovement.objects.filter(
                entreprise=self.entreprise,
                produit=self.product_a,
                movement_type=StockMovement.MovementType.ADJUSTMENT_NEGATIVE,
                source_model="InventoryLine",
                source_id=line.id,
            ).exists()
        )

    def test_validate_inventory_without_difference_creates_no_adjustment(self):
        session = create_inventory_session(entreprise=self.entreprise, name="Inventaire stable", utilisateur=self.owner)

        start_inventory_session(entreprise=self.entreprise, session_id=session.id)
        for line in session.lines.all():
            record_inventory_count(
                entreprise=self.entreprise,
                session_id=session.id,
                line_id=line.id,
                counted_quantity=line.theoretical_quantity,
                comment="",
            )
        close_inventory_session(entreprise=self.entreprise, session_id=session.id)
        validate_inventory_session(entreprise=self.entreprise, session_id=session.id, utilisateur=self.owner)

        self.assertFalse(
            StockMovement.objects.filter(
                entreprise=self.entreprise,
                source_model="InventoryLine",
            ).exists()
        )

    def test_validation_requires_all_lines_to_be_counted_and_prevents_double_validation(self):
        session = create_inventory_session(entreprise=self.entreprise, name="Inventaire strict", utilisateur=self.owner)

        start_inventory_session(entreprise=self.entreprise, session_id=session.id)
        line = session.lines.get(produit=self.product_a)
        record_inventory_count(entreprise=self.entreprise, session_id=session.id, line_id=line.id, counted_quantity=10, comment="")
        close_inventory_session(entreprise=self.entreprise, session_id=session.id)

        with self.assertRaises(InventoryOperationError):
            validate_inventory_session(entreprise=self.entreprise, session_id=session.id, utilisateur=self.owner)

        other_line = session.lines.get(produit=self.product_b)
        session.status = InventorySession.Status.IN_PROGRESS
        session.save(update_fields=["status"])
        record_inventory_count(entreprise=self.entreprise, session_id=session.id, line_id=other_line.id, counted_quantity=5, comment="")
        close_inventory_session(entreprise=self.entreprise, session_id=session.id)
        validate_inventory_session(entreprise=self.entreprise, session_id=session.id, utilisateur=self.owner)

        with self.assertRaises(InventoryOperationError):
            validate_inventory_session(entreprise=self.entreprise, session_id=session.id, utilisateur=self.owner)

    def test_cancel_inventory_prevents_future_modifications_and_is_scoped_to_tenant(self):
        session = create_inventory_session(entreprise=self.entreprise, name="Inventaire annule", utilisateur=self.owner)
        cancel_inventory_session(entreprise=self.entreprise, session_id=session.id)
        session.refresh_from_db()
        self.assertEqual(session.status, InventorySession.Status.CANCELLED)
        line = session.lines.get(produit=self.product_a)

        with self.assertRaises(InventoryOperationError):
            record_inventory_count(entreprise=self.entreprise, session_id=session.id, line_id=line.id, counted_quantity=9, comment="")

        with self.assertRaises(InventoryOperationError):
            record_inventory_count(entreprise=self.autre_entreprise, session_id=session.id, line_id=line.id, counted_quantity=9, comment="")

    def test_inventory_session_date_filters_do_not_emit_naive_datetime_warnings(self):
        create_inventory_session(entreprise=self.entreprise, name="Inventaire date", utilisateur=self.owner)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            list(
                get_inventory_sessions_for_entreprise(
                    self.entreprise,
                    date_debut=date.today(),
                    date_fin=date.today(),
                )
            )

        self.assertFalse(
            any(
                issubclass(warning.category, RuntimeWarning)
                and "naive datetime" in str(warning.message).lower()
                for warning in caught
            )
        )


class InventoryViewsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Inventaire UI")
        self.autre_entreprise = create_entreprise("Entreprise Inventaire UI B")
        self.owner = create_user("owner-inventory-ui", "proprietaire", self.entreprise)
        self.gestionnaire = create_user("manager-inventory-ui", "gestionnaire", self.entreprise)
        self.comptable = create_user("accountant-inventory-ui", "comptable", self.entreprise)
        self.owner_b = create_user("owner-inventory-ui-b", "proprietaire", self.autre_entreprise)
        self.plan = Abonnement.objects.create(nom="Produits Inventaire", code="products", prix=10, duree_jours=30, actif=True)
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.owner)
        activate_subscription_for_entreprise(entreprise=self.autre_entreprise, plan=self.plan, utilisateur=self.owner_b)
        self.product = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Serveur",
            reference="INV-V-1",
            prix_unitaire=Decimal("600.00"),
            quantite_stock=9,
            seuil_alerte=1,
            actif=True,
        )

    def _count_post_data(self, session, counted_quantity):
        line = session.lines.get(produit=self.product)
        return {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-line_id": str(line.id),
            "form-0-counted_quantity": str(counted_quantity),
            "form-0-comment": "Compte manuellement",
        }

    def test_stock_view_user_can_list_inventories(self):
        session = create_inventory_session(entreprise=self.entreprise, name="Inventaire vue", utilisateur=self.owner)
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("inventory_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, session.name)

    def test_inventory_create_detail_and_count_flow(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.post(
            reverse("inventory_create"),
            {"name": "Inventaire mai", "comment": "Campagne mensuelle"},
        )
        self.assertEqual(response.status_code, 302)
        session = InventorySession.objects.get(entreprise=self.entreprise, name="Inventaire mai")

        detail_response = self.client.get(reverse("inventory_detail", args=[session.id]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Inventaire mai")

        count_response = self.client.post(
            reverse("inventory_count", args=[session.id]),
            self._count_post_data(session, 11),
        )
        self.assertEqual(count_response.status_code, 302)
        line = session.lines.get(produit=self.product)
        line.refresh_from_db()
        self.assertEqual(line.counted_quantity, 11)
        self.assertEqual(line.difference, 2)

    def test_inventory_validate_generates_adjustment_via_view(self):
        session = create_inventory_session(entreprise=self.entreprise, name="Inventaire valider", utilisateur=self.owner)

        start_inventory_session(entreprise=self.entreprise, session_id=session.id)
        line = session.lines.get(produit=self.product)
        record_inventory_count(entreprise=self.entreprise, session_id=session.id, line_id=line.id, counted_quantity=12, comment="")
        self.client.force_login(self.gestionnaire)
        close_response = self.client.post(reverse("inventory_close", args=[session.id]))
        self.assertEqual(close_response.status_code, 302)
        validate_response = self.client.post(reverse("inventory_validate", args=[session.id]))
        self.assertEqual(validate_response.status_code, 302)
        self.assertTrue(
            StockMovement.objects.filter(
                entreprise=self.entreprise,
                produit=self.product,
                movement_type=StockMovement.MovementType.ADJUSTMENT_POSITIVE,
                source_id=line.id,
            ).exists()
        )

    def test_inventory_permissions_are_enforced(self):
        session = create_inventory_session(entreprise=self.entreprise, name="Inventaire permissions", utilisateur=self.owner)
        self.client.force_login(self.comptable)
        self.assertEqual(self.client.get(reverse("inventory_detail", args=[session.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("inventory_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("inventory_count", args=[session.id])).status_code, 403)
        self.assertEqual(self.client.post(reverse("inventory_close", args=[session.id])).status_code, 403)
        self.assertEqual(self.client.post(reverse("inventory_validate", args=[session.id])).status_code, 403)
        self.assertEqual(self.client.post(reverse("inventory_cancel", args=[session.id])).status_code, 403)
