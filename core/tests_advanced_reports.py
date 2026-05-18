from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import patch

from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from core.selectors.reports import get_financial_summary, get_payment_analysis, get_sales_analysis, get_stock_analysis
from core.services.product_policy import can_access_module
from core.services.reports import build_advanced_report_payload
from core.services.subscription import (
    activate_free_plan_for_entreprise,
    activate_subscription_for_entreprise,
    get_default_paid_plans,
    get_or_create_free_plan,
)
from joatham_billing.models import PaiementFacture
from joatham_billing.services.facturation import create_facture
from joatham_billing.tests.factories import create_client, create_entreprise, create_user
from joatham_depenses.models import Depense
from joatham_payments.models import PaymentTransaction
from joatham_products.models import Produit
from joatham_users.models import Abonnement


def create_default_plan(code):
    payload = next(plan for plan in get_default_paid_plans() if plan["code"] == code)
    return Abonnement.objects.create(**payload, actif=True)


class AdvancedReportsAccessTests(TestCase):
    def setUp(self):
        self.free_company = create_entreprise("Rapports Free")
        self.starter_company = create_entreprise("Rapports Starter")
        self.pro_company = create_entreprise("Rapports Pro")
        self.premium_company = create_entreprise("Rapports Premium")
        self.free_owner = create_user("owner-adv-free", "proprietaire", self.free_company)
        self.starter_owner = create_user("owner-adv-starter", "proprietaire", self.starter_company)
        self.pro_owner = create_user("owner-adv-pro", "proprietaire", self.pro_company)
        self.premium_owner = create_user("owner-adv-premium", "proprietaire", self.premium_company)

        activate_free_plan_for_entreprise(
            entreprise=self.free_company,
            plan=get_or_create_free_plan(),
            utilisateur=self.free_owner,
        )
        activate_subscription_for_entreprise(
            entreprise=self.starter_company,
            plan=create_default_plan("starter"),
            utilisateur=self.starter_owner,
        )
        activate_subscription_for_entreprise(
            entreprise=self.pro_company,
            plan=create_default_plan("pro"),
            utilisateur=self.pro_owner,
        )
        activate_subscription_for_entreprise(
            entreprise=self.premium_company,
            plan=create_default_plan("premium"),
            utilisateur=self.premium_owner,
        )

    def test_only_premium_can_access_advanced_report_modules(self):
        for user in (self.free_owner, self.starter_owner, self.pro_owner):
            self.assertFalse(can_access_module(user, "advanced_reports"))
            self.assertFalse(can_access_module(user, "advanced_reports_exports"))
            self.assertFalse(can_access_module(user, "business_dashboard"))

        self.assertTrue(can_access_module(self.premium_owner, "advanced_reports"))
        self.assertTrue(can_access_module(self.premium_owner, "advanced_reports_exports"))
        self.assertTrue(can_access_module(self.premium_owner, "business_dashboard"))

    def test_advanced_reports_view_is_blocked_before_premium(self):
        for user in (self.free_owner, self.starter_owner, self.pro_owner):
            self.client.force_login(user)
            response = self.client.get(reverse("advanced_reports"))
            self.assertEqual(response.status_code, 302)
            self.assertIn("module=advanced_reports", response["Location"])
            self.assertIn("reason=premium_required", response["Location"])

    def test_premium_can_open_advanced_reports_and_exports(self):
        self.client.force_login(self.premium_owner)
        self.assertEqual(self.client.get(reverse("advanced_reports")).status_code, 200)
        excel_response = self.client.get(reverse("advanced_reports_export_excel"))
        self.assertEqual(excel_response.status_code, 200)
        self.assertEqual(
            excel_response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        workbook = ZipFile(BytesIO(excel_response.content))
        sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("Chiffre d", sheet_xml)

    @patch("core.reports_views.render_pdf_response")
    def test_premium_pdf_export_uses_advanced_report_template(self, mock_render_pdf):
        mock_render_pdf.return_value = HttpResponse(b"%PDF-1.4", content_type="application/pdf")
        self.client.force_login(self.premium_owner)
        response = self.client.get(reverse("advanced_reports_export_pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_render_pdf.call_args[0][1], "core/advanced_reports_pdf.html")

    def test_navigation_locks_advanced_reports_for_pro_and_links_premium(self):
        self.client.force_login(self.pro_owner)
        pro_response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(pro_response, "Rapports avances")
        self.assertContains(pro_response, "Premium")
        self.assertNotContains(pro_response, reverse("advanced_reports"))

        self.client.force_login(self.premium_owner)
        premium_response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(premium_response, reverse("advanced_reports"))


class AdvancedReportsCalculationTests(TestCase):
    def setUp(self):
        self.entreprise = create_entreprise("Rapports Calcul")
        self.other_entreprise = create_entreprise("Rapports Calcul B")
        self.owner = create_user("owner-adv-calc", "proprietaire", self.entreprise)
        self.other_owner = create_user("owner-adv-calc-b", "proprietaire", self.other_entreprise)
        premium_plan = create_default_plan("premium")
        activate_subscription_for_entreprise(entreprise=self.entreprise, plan=premium_plan, utilisateur=self.owner)
        activate_subscription_for_entreprise(entreprise=self.other_entreprise, plan=premium_plan, utilisateur=self.other_owner)
        self.client_obj = create_client(self.entreprise, "Client Decision")
        self.other_client = create_client(self.other_entreprise, "Client Externe")

        self.partial_invoice = create_facture(
            entreprise=self.entreprise,
            user=self.owner,
            client_id=self.client_obj.id,
            tva=Decimal("0"),
            lignes=[{"designation": "Audit process", "quantite": 1, "prix": Decimal("100.00")}],
        )
        self.paid_invoice = create_facture(
            entreprise=self.entreprise,
            user=self.owner,
            client_id=self.client_obj.id,
            tva=Decimal("0"),
            lignes=[{"designation": "Service support", "quantite": 1, "prix": Decimal("50.00")}],
        )
        PaiementFacture.objects.create(
            facture=self.partial_invoice,
            montant=Decimal("40.00"),
            mode=PaiementFacture.ModePaiement.ESPECES,
            statut=PaiementFacture.StatutPaiement.VALIDE,
        )
        PaiementFacture.objects.create(
            facture=self.paid_invoice,
            montant=Decimal("50.00"),
            mode=PaiementFacture.ModePaiement.ESPECES,
            statut=PaiementFacture.StatutPaiement.VALIDE,
        )
        PaymentTransaction.objects.create(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.MPESA,
            amount=Decimal("15.00"),
            currency="CDF",
            status=PaymentTransaction.Status.CONFIRME,
            reference="MPESA-ADV",
        )
        PaymentTransaction.objects.create(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.ORANGE_MONEY,
            amount=Decimal("30.00"),
            currency="CDF",
            status=PaymentTransaction.Status.EN_ATTENTE,
            reference="OM-PENDING",
        )
        PaymentTransaction.objects.create(
            entreprise=self.entreprise,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            method=PaymentTransaction.Method.CARD,
            amount=Decimal("12.00"),
            currency="CDF",
            status=PaymentTransaction.Status.REJETE,
            reference="CARD-REJECT",
        )
        Depense.objects.create(entreprise=self.entreprise, description="Internet", montant=Decimal("30.00"))
        Produit.objects.create(
            entreprise=self.entreprise,
            nom="Produit faible",
            reference="ADV-LOW",
            prix_unitaire=Decimal("20.00"),
            quantite_stock=1,
            seuil_alerte=2,
        )
        Produit.objects.create(
            entreprise=self.entreprise,
            nom="Produit rupture",
            reference="ADV-OUT",
            prix_unitaire=Decimal("10.00"),
            quantite_stock=0,
            seuil_alerte=1,
        )

        other_invoice = create_facture(
            entreprise=self.other_entreprise,
            user=self.other_owner,
            client_id=self.other_client.id,
            tva=Decimal("0"),
            lignes=[{"designation": "Hors scope", "quantite": 1, "prix": Decimal("999.00")}],
        )
        PaiementFacture.objects.create(
            facture=other_invoice,
            montant=Decimal("999.00"),
            mode=PaiementFacture.ModePaiement.ESPECES,
            statut=PaiementFacture.StatutPaiement.VALIDE,
        )
        Depense.objects.create(entreprise=self.other_entreprise, description="Externe", montant=Decimal("999.00"))
        Produit.objects.create(
            entreprise=self.other_entreprise,
            nom="Produit externe",
            reference="ADV-EXT",
            prix_unitaire=Decimal("999.00"),
            quantite_stock=0,
            seuil_alerte=1,
        )

        self.filters = {
            "date_debut": None,
            "date_fin": None,
            "currency": "CDF",
            "caisse": None,
            "invoice_status": "",
            "payment_status": "",
            "payment_method": "",
            "group_by": "day",
        }

    def test_financial_summary_calculates_global_totals_and_isolation(self):
        summary = get_financial_summary(self.entreprise, self.filters)
        self.assertEqual(summary["revenue_total"], Decimal("150.00"))
        self.assertEqual(summary["collected_total"], Decimal("105.00"))
        self.assertEqual(summary["remaining_total"], Decimal("60.00"))
        self.assertEqual(summary["expenses_total"], Decimal("30.00"))
        self.assertEqual(summary["net_balance"], Decimal("75.00"))
        self.assertEqual(summary["invoice_count"], 2)
        self.assertEqual(summary["paid_invoice_count"], 1)
        self.assertEqual(summary["unpaid_invoice_count"], 1)
        self.assertEqual(summary["pending_payment_count"], 1)

    def test_financial_reports_use_invoice_total_net_with_reductions(self):
        create_facture(
            entreprise=self.entreprise,
            user=self.owner,
            client_id=self.client_obj.id,
            tva=Decimal("16"),
            remise=Decimal("10"),
            lignes=[{"designation": "Formation avec remise", "quantite": 1, "prix": Decimal("100.00")}],
        )

        summary = get_financial_summary(self.entreprise, self.filters)
        self.assertEqual(summary["revenue_total"], Decimal("256.00"))
        self.assertEqual(summary["remaining_total"], Decimal("166.00"))

        sales = get_sales_analysis(self.entreprise, self.filters)
        self.assertEqual(sales["evolution"][0]["total"], Decimal("256.00"))
        self.assertEqual(sales["top_clients"][0]["total"], Decimal("256.00"))

    def test_payment_method_and_status_breakdown(self):
        payments = get_payment_analysis(self.entreprise, self.filters)
        method_totals = {row["code"]: row for row in payments["method_breakdown"]}
        status_totals = {row["code"]: row for row in payments["status_breakdown"]}
        self.assertEqual(method_totals["cash"]["confirmed_total"], Decimal("90.00"))
        self.assertEqual(method_totals["mpesa"]["confirmed_total"], Decimal("15.00"))
        self.assertEqual(payments["total_mobile_money"], Decimal("15.00"))
        self.assertEqual(status_totals["confirme"]["count"], 3)
        self.assertEqual(status_totals["en_attente"]["count"], 1)
        self.assertEqual(status_totals["rejete"]["count"], 1)

    def test_stock_low_and_out_of_stock_are_scoped(self):
        stock = get_stock_analysis(self.entreprise, self.filters)
        self.assertEqual(stock["low_stock_count"], 1)
        self.assertEqual(stock["out_of_stock_count"], 1)
        self.assertEqual(stock["stock_value"], Decimal("20.00"))

    def test_payload_contains_management_indicators(self):
        payload = build_advanced_report_payload(self.entreprise, self.filters)
        self.assertEqual(payload["management"]["payment_rate"], 50.0)
        self.assertEqual(payload["management"]["unpaid_rate"], 50.0)
        self.assertEqual(payload["management"]["simplified_margin"], Decimal("75.00"))
