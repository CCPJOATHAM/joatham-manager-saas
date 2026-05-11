from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from core.services.subscription import activate_subscription_for_entreprise, get_default_paid_plans
from joatham_billing.tests.factories import create_entreprise, create_user
from joatham_caisse.models import Caisse
from joatham_caisse.selectors.reports import get_cash_report_snapshot
from joatham_caisse.services.mouvements import (
    record_cash_entry,
    record_cash_expense,
    record_cash_exit,
    record_invoice_cash_payment,
)
from joatham_caisse.services.session import close_session, open_session
from joatham_caisse.services.validation import validate_session
from joatham_users.models import Abonnement


class CashReportsSelectorTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Rapport Caisse")
        self.autre_entreprise = create_entreprise("Entreprise Rapport Externe")
        self.owner = create_user("owner-report-cash", "proprietaire", self.entreprise)
        self.other_owner = create_user("owner-report-cash-b", "proprietaire", self.autre_entreprise)
        self.caisse = Caisse.objects.create(
            entreprise=self.entreprise,
            nom="Caisse rapport",
            code="REP-001",
            devise="CDF",
            cree_par=self.owner,
        )
        self.second_caisse = Caisse.objects.create(
            entreprise=self.entreprise,
            nom="Caisse rapport secondaire",
            code="REP-002",
            devise="CDF",
            cree_par=self.owner,
        )
        self.other_caisse = Caisse.objects.create(
            entreprise=self.autre_entreprise,
            nom="Caisse externe",
            code="REP-EXT",
            devise="CDF",
            cree_par=self.other_owner,
        )
        self.open_session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("100.00"),
        )
        self.validated_session = open_session(
            entreprise=self.entreprise,
            caisse=self.second_caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("80.00"),
        )
        record_cash_entry(
            entreprise=self.entreprise,
            caisse=self.validated_session.caisse,
            session=self.validated_session,
            montant=Decimal("10.00"),
            libelle="Entree fermee",
            utilisateur=self.owner,
        )
        close_session(
            entreprise=self.entreprise,
            session=self.validated_session,
            utilisateur=self.owner,
            solde_reel=Decimal("95.00"),
        )
        validate_session(
            entreprise=self.entreprise,
            session=self.validated_session,
            utilisateur=self.owner,
        )
        self.validated_session.refresh_from_db()

        record_cash_entry(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.open_session,
            montant=Decimal("50.00"),
            libelle="Vente comptoir",
            utilisateur=self.owner,
        )
        record_cash_exit(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.open_session,
            montant=Decimal("20.00"),
            libelle="Sortie caisse",
            utilisateur=self.owner,
        )
        record_cash_expense(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.open_session,
            montant=Decimal("15.00"),
            libelle="Depense bureautique",
            utilisateur=self.owner,
        )
        record_invoice_cash_payment(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.open_session,
            montant=Decimal("40.00"),
            libelle="Paiement facture client",
            utilisateur=self.owner,
        )

        external_session = open_session(
            entreprise=self.autre_entreprise,
            caisse=self.other_caisse,
            utilisateur=self.other_owner,
            solde_initial=Decimal("100.00"),
        )
        record_cash_entry(
            entreprise=self.autre_entreprise,
            caisse=self.other_caisse,
            session=external_session,
            montant=Decimal("999.00"),
            libelle="Externe",
            utilisateur=self.other_owner,
        )

    def test_report_snapshot_returns_expected_totals(self):
        report = get_cash_report_snapshot(self.entreprise)
        self.assertEqual(report["total_entrees"], Decimal("100.00"))
        self.assertEqual(report["total_sorties"], Decimal("35.00"))
        self.assertEqual(report["total_depenses_caisse"], Decimal("15.00"))
        self.assertEqual(report["total_paiements_factures"], Decimal("40.00"))
        self.assertEqual(report["solde_net"], Decimal("65.00"))
        self.assertEqual(report["nombre_mouvements"], 5)

    def test_report_snapshot_counts_sessions_and_ecarts(self):
        report = get_cash_report_snapshot(self.entreprise)
        self.assertEqual(report["sessions_ouvertes"], 1)
        self.assertEqual(report["sessions_fermees"], 0)
        self.assertEqual(report["sessions_validees"], 1)
        self.assertEqual(report["ecarts_positifs"], 1)
        self.assertEqual(report["ecarts_negatifs"], 0)

    def test_report_snapshot_is_scoped_to_entreprise(self):
        report = get_cash_report_snapshot(self.entreprise)
        self.assertEqual(len(report["summary_by_caisse"]), 2)
        self.assertEqual(sum(item["count"] for item in report["summary_by_type"]), 5)


class CashReportsViewsTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Entreprise Vue Rapport")
        self.owner = create_user("owner-view-report", "proprietaire", self.entreprise)
        pro_payload = next(plan for plan in get_default_paid_plans() if plan["code"] == "pro")
        self.pro_plan = Abonnement.objects.create(**pro_payload, actif=True)
        self.caisse = Caisse.objects.create(
            entreprise=self.entreprise,
            nom="Caisse vue",
            code="VIEW-001",
            devise="CDF",
            cree_par=self.owner,
        )
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=self.pro_plan, utilisateur=self.owner)
        self.session = open_session(
            entreprise=self.entreprise,
            caisse=self.caisse,
            utilisateur=self.owner,
            solde_initial=Decimal("50.00"),
        )
        record_cash_entry(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.session,
            montant=Decimal("20.00"),
            libelle="Encaissement test",
            utilisateur=self.owner,
        )
        record_cash_expense(
            entreprise=self.entreprise,
            caisse=self.caisse,
            session=self.session,
            montant=Decimal("7.00"),
            libelle="Papeterie",
            reference="DEP-001",
            utilisateur=self.owner,
        )
        self.autre_entreprise = create_entreprise("Entreprise Vue Rapport B")
        self.autre_owner = create_user("owner-view-report-b", "proprietaire", self.autre_entreprise)
        self.autre_caisse = Caisse.objects.create(
            entreprise=self.autre_entreprise,
            nom="Caisse externe",
            code="VIEW-EXT",
            devise="CDF",
            cree_par=self.autre_owner,
        )
        activate_subscription_for_entreprise(entreprise=self.autre_entreprise, plan=self.pro_plan, utilisateur=self.autre_owner)
        self.autre_session = open_session(
            entreprise=self.autre_entreprise,
            caisse=self.autre_caisse,
            utilisateur=self.autre_owner,
            solde_initial=Decimal("30.00"),
        )
        record_cash_entry(
            entreprise=self.autre_entreprise,
            caisse=self.autre_caisse,
            session=self.autre_session,
            montant=Decimal("99.00"),
            libelle="Externe",
            utilisateur=self.autre_owner,
        )
        self.client.force_login(self.owner)

    def test_reports_page_renders_successfully(self):
        response = self.client.get(reverse("caisse_reports"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("report", response.context)

    def test_session_and_movement_list_pages_render_successfully(self):
        response = self.client.get(reverse("caisse_session_list"), {"statut": "ouverte"})
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("caisse_movement_list"), {"type_mouvement": "entree"})
        self.assertEqual(response.status_code, 200)

    def test_movement_export_excel_returns_xlsx_response(self):
        response = self.client.get(reverse("caisse_movement_export_excel"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("mouvements-caisse.xlsx", response["Content-Disposition"])

    def test_movement_export_excel_applies_filters_and_scope(self):
        response = self.client.get(reverse("caisse_movement_export_excel"), {"q": "Papeterie"})
        workbook = ZipFile(BytesIO(response.content))
        sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("Papeterie", sheet_xml)
        self.assertNotIn("Encaissement test", sheet_xml)
        self.assertNotIn("Externe", sheet_xml)

    def test_cash_reports_export_pdf_returns_pdf_response(self):
        response = self.client.get(reverse("caisse_reports_export_pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("rapport-caisse.pdf", response["Content-Disposition"])

    @patch("joatham_caisse.views.render_pdf_response")
    def test_cash_reports_export_pdf_uses_scoped_aggregates(self, mock_render_pdf):
        mock_render_pdf.return_value = HttpResponse(b"%PDF-1.4", content_type="application/pdf")
        response = self.client.get(reverse("caisse_reports_export_pdf"))
        self.assertEqual(response.status_code, 200)
        _, template_name, context = mock_render_pdf.call_args[0][:3]
        self.assertEqual(template_name, "joatham_caisse/reports_pdf.html")
        self.assertEqual(context["report"]["nombre_mouvements"], 2)
        self.assertEqual(context["report"]["total_entrees"], Decimal("20.00"))
        self.assertEqual(context["report"]["total_depenses_caisse"], Decimal("7.00"))
        self.assertTrue(all(item.entreprise_id == self.entreprise.id for item in context["recent_movements"]))
