from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import patch

from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from core.services.subscription import activate_subscription_for_entreprise
from joatham_billing.models import Facture
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_users.models import Abonnement

from .models import Produit, StockMovement
from .selectors.reports import (
    get_recent_stock_activity,
    get_stock_report_inventory_summary,
    get_stock_report_movement_type_summary,
    get_stock_report_product_summary,
    get_stock_report_snapshot,
)
from .services.inventory import (
    close_inventory_session,
    create_inventory_session,
    record_inventory_count,
    start_inventory_session,
    validate_inventory_session,
)
from .services.stock import apply_invoice_sale, apply_manual_entry, apply_manual_exit


class StockReportsSelectorsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Rapport Stock")
        self.autre_entreprise = create_entreprise("Entreprise Rapport Stock B")
        self.owner = create_user("owner-stock-report", "proprietaire", self.entreprise)
        self.owner_b = create_user("owner-stock-report-b", "proprietaire", self.autre_entreprise)
        self.product = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Switch coeur",
            reference="REP-ST-1",
            prix_unitaire=Decimal("200.00"),
            quantite_stock=10,
            seuil_alerte=2,
            actif=True,
        )
        self.product_low = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Point d'acces",
            reference="REP-ST-2",
            prix_unitaire=Decimal("90.00"),
            quantite_stock=1,
            seuil_alerte=2,
            actif=True,
        )
        self.product_out = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Telephone IP",
            reference="REP-ST-3",
            prix_unitaire=Decimal("70.00"),
            quantite_stock=0,
            seuil_alerte=1,
            actif=True,
        )
        self.external_product = Produit.objects.create(
            entreprise=self.autre_entreprise,
            nom="Produit externe",
            reference="REP-EXT-1",
            prix_unitaire=Decimal("50.00"),
            quantite_stock=9,
            seuil_alerte=1,
            actif=True,
        )
        self.manual_entry = apply_manual_entry(
            entreprise=self.entreprise,
            produit=self.product,
            quantity=4,
            utilisateur=self.owner,
            reference="ENT-R1",
            reason="Reappro",
        )
        self.manual_exit = apply_manual_exit(
            entreprise=self.entreprise,
            produit=self.product,
            quantity=3,
            utilisateur=self.owner,
            reference="SOR-R1",
            reason="Sortie test",
        )
        self.facture = Facture.objects.create(
            entreprise=self.entreprise,
            client_nom="Client test",
            tva=Decimal("0"),
            montant=Decimal("0"),
            description="",
        )
        self.invoice_sale = apply_invoice_sale(
            entreprise=self.entreprise,
            produit=self.product_low,
            quantity=1,
            facture=self.facture,
            utilisateur=self.owner,
        )
        self.inventory = create_inventory_session(
            entreprise=self.entreprise,
            name="Inventaire mensuel",
            utilisateur=self.owner,
        )
        start_inventory_session(entreprise=self.entreprise, session_id=self.inventory.id)
        for line in self.inventory.lines.all():
            counted = line.theoretical_quantity
            if line.produit_id == self.product.id:
                counted = line.theoretical_quantity + 2
            record_inventory_count(
                entreprise=self.entreprise,
                session_id=self.inventory.id,
                line_id=line.id,
                counted_quantity=counted,
                comment="Controle",
            )
        close_inventory_session(entreprise=self.entreprise, session_id=self.inventory.id)
        validate_inventory_session(entreprise=self.entreprise, session_id=self.inventory.id, utilisateur=self.owner)

        apply_manual_entry(
            entreprise=self.autre_entreprise,
            produit=self.external_product,
            quantity=5,
            utilisateur=self.owner_b,
            reference="EXT-R1",
            reason="Externe",
        )

    def test_snapshot_global_is_scoped_and_returns_expected_totals(self):
        snapshot = get_stock_report_snapshot(self.entreprise)
        self.assertEqual(snapshot["total_produits_actifs"], 3)
        self.assertEqual(snapshot["produits_en_stock"], 1)
        self.assertEqual(snapshot["produits_stock_faible"], 2)
        self.assertEqual(snapshot["produits_rupture"], 2)
        self.assertEqual(snapshot["total_mouvements"], 4)
        self.assertEqual(snapshot["total_entrees"], 6)
        self.assertEqual(snapshot["total_sorties"], 4)
        self.assertEqual(snapshot["inventaires_valides"], 1)
        self.assertEqual(snapshot["inventaires_avec_ecarts"], 1)

    def test_product_summary_can_filter_by_product_and_source(self):
        summary = get_stock_report_product_summary(
            self.entreprise,
            produit=self.product_low,
            source_app="joatham_billing",
        )
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["product"].id, self.product_low.id)
        self.assertEqual(summary[0]["total_sorties"], 1)
        self.assertEqual(summary[0]["total_entrees"], 0)

    def test_movement_type_summary_and_recent_activity_support_filters(self):
        type_summary = get_stock_report_movement_type_summary(
            self.entreprise,
            movement_type=StockMovement.MovementType.INVOICE_SALE,
        )
        self.assertEqual(len(type_summary), 1)
        self.assertEqual(type_summary[0]["movement_type"], StockMovement.MovementType.INVOICE_SALE)
        self.assertEqual(type_summary[0]["total_quantity"], 1)

        recent = list(get_recent_stock_activity(self.entreprise, source_app="joatham_billing"))
        self.assertEqual([movement.id for movement in recent], [self.invoice_sale.id])

    def test_inventory_summary_reports_validated_differences_only_for_entreprise(self):
        summary = get_stock_report_inventory_summary(self.entreprise)
        self.assertEqual(summary["validated_count"], 1)
        self.assertEqual(summary["inventories_with_differences"], 1)
        self.assertGreaterEqual(summary["positive_differences"], 1)


class StockReportsViewsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Vue Stock")
        self.autre_entreprise = create_entreprise("Entreprise Vue Stock B")
        self.owner = create_user("owner-stock-report-view", "proprietaire", self.entreprise)
        self.comptable = create_user("accountant-stock-report-view", "comptable", self.entreprise)
        self.gestionnaire = create_user("manager-stock-report-view", "gestionnaire", self.entreprise)
        self.owner_b = create_user("owner-stock-report-view-b", "proprietaire", self.autre_entreprise)
        self.plan = Abonnement.objects.create(nom="Produits rapports", code="products", prix=10, duree_jours=30, actif=True)
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.plan, utilisateur=self.owner)
        activate_subscription_for_entreprise(entreprise=self.autre_entreprise, plan=self.plan, utilisateur=self.owner_b)
        self.product = Produit.objects.create(
            entreprise=self.entreprise,
            nom="Serveur rack",
            reference="VIEW-ST-1",
            prix_unitaire=Decimal("800.00"),
            quantite_stock=12,
            seuil_alerte=2,
            actif=True,
        )
        self.external_product = Produit.objects.create(
            entreprise=self.autre_entreprise,
            nom="Routeur externe",
            reference="VIEW-ST-X",
            prix_unitaire=Decimal("60.00"),
            quantite_stock=5,
            seuil_alerte=1,
            actif=True,
        )
        self.movement = apply_manual_entry(
            entreprise=self.entreprise,
            produit=self.product,
            quantity=3,
            utilisateur=self.owner,
            reference="EXCEL-1",
            reason="Livraison rack",
        )
        self.inventory = create_inventory_session(
            entreprise=self.entreprise,
            name="Inventaire export",
            utilisateur=self.owner,
        )
        start_inventory_session(entreprise=self.entreprise, session_id=self.inventory.id)
        line = self.inventory.lines.get(produit=self.product)
        record_inventory_count(
            entreprise=self.entreprise,
            session_id=self.inventory.id,
            line_id=line.id,
            counted_quantity=line.theoretical_quantity + 1,
            comment="Une unite en plus",
        )
        close_inventory_session(entreprise=self.entreprise, session_id=self.inventory.id)
        validate_inventory_session(entreprise=self.entreprise, session_id=self.inventory.id, utilisateur=self.owner)
        self.external_inventory = create_inventory_session(
            entreprise=self.autre_entreprise,
            name="Inventaire externe",
            utilisateur=self.owner_b,
        )
        apply_manual_entry(
            entreprise=self.autre_entreprise,
            produit=self.external_product,
            quantity=2,
            utilisateur=self.owner_b,
            reference="EXT-EXCEL",
            reason="Externe",
        )

    def test_stock_reports_page_is_accessible_with_stock_view(self):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("stock_reports"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("report", response.context)

    def test_stock_reports_page_requires_permission(self):
        response = self.client.get(reverse("stock_reports"))
        self.assertEqual(response.status_code, 302)

    def test_stock_movement_export_excel_requires_export_permission(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("stock_movement_export_excel"))
        self.assertEqual(response.status_code, 403)

    def test_stock_movement_export_excel_returns_scoped_filtered_xlsx(self):
        self.client.force_login(self.comptable)
        response = self.client.get(
            reverse("stock_movement_export_excel"),
            {"produit": str(self.product.id), "source_app": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("mouvements-stock.xlsx", response["Content-Disposition"])
        workbook = ZipFile(BytesIO(response.content))
        sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("Serveur rack", sheet_xml)
        self.assertIn("Livraison rack", sheet_xml)
        self.assertNotIn("Routeur externe", sheet_xml)

    def test_inventory_export_excel_returns_scoped_filtered_xlsx(self):
        self.client.force_login(self.comptable)
        response = self.client.get(
            reverse("inventory_export_excel"),
            {"status": "validated"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("inventaires-stock.xlsx", response["Content-Disposition"])
        workbook = ZipFile(BytesIO(response.content))
        sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("Inventaire export", sheet_xml)
        self.assertIn("Serveur rack", sheet_xml)
        self.assertNotIn("Inventaire externe", sheet_xml)

    def test_inventory_export_excel_requires_export_permission(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("inventory_export_excel"))
        self.assertEqual(response.status_code, 403)

    @patch("joatham_products.views.render_pdf_response")
    def test_stock_reports_export_pdf_uses_scoped_context(self, mock_render_pdf):
        mock_render_pdf.return_value = HttpResponse(b"%PDF-1.4", content_type="application/pdf")
        self.client.force_login(self.comptable)
        response = self.client.get(reverse("stock_reports_export_pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_render_pdf.call_args[0][1], "joatham_products/stock_reports_pdf.html")
        context = mock_render_pdf.call_args[0][2]
        self.assertEqual(context["report"]["inventaires_valides"], 1)
        self.assertTrue(all(item.produit.entreprise_id == self.entreprise.id for item in context["recent_movements"]))

    def test_stock_reports_export_pdf_requires_export_permission(self):
        self.client.force_login(self.gestionnaire)
        response = self.client.get(reverse("stock_reports_export_pdf"))
        self.assertEqual(response.status_code, 403)
