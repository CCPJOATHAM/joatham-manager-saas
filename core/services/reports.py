from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date

from core.selectors.reports import (
    PAYMENT_METHODS,
    PAYMENT_STATUS_LABELS,
    get_accounting_analysis,
    get_available_report_currencies,
    get_cash_analysis,
    get_expense_analysis,
    get_financial_summary,
    get_management_indicators,
    get_payment_analysis,
    get_report_caisses,
    get_sales_analysis,
    get_stock_analysis,
)
from core.services.currency import format_amount_for_entreprise, format_decimal_number, get_currency_code
from joatham_billing.models import Facture


PERIOD_CHOICES = [
    ("today", "Aujourd'hui"),
    ("this_week", "Cette semaine"),
    ("this_month", "Ce mois"),
    ("this_quarter", "Ce trimestre"),
    ("this_year", "Cette annee"),
    ("custom", "Personnalise"),
]
INVOICE_STATUS_CHOICES = [
    ("", "Tous les statuts"),
    (Facture.Statut.BROUILLON, "Brouillon"),
    (Facture.Statut.EMISE, "Emise"),
    (Facture.Statut.PAYEE, "Payee"),
    (Facture.Statut.ANNULEE, "Annulee"),
    ("impaye", "Impayee"),
    ("partielle", "Partiellement payee"),
]
PAYMENT_STATUS_CHOICES = [("", "Tous les statuts")] + list(PAYMENT_STATUS_LABELS.items())
PAYMENT_METHOD_CHOICES = [("", "Tous les moyens")] + [(item["code"], item["label"]) for item in PAYMENT_METHODS]


def _quarter_start(today):
    first_month = ((today.month - 1) // 3) * 3 + 1
    return today.replace(month=first_month, day=1)


def _period_dates(period, today):
    if period == "today":
        return today, today
    if period == "this_week":
        return today - timedelta(days=today.weekday()), today
    if period == "this_month":
        return today.replace(day=1), today
    if period == "this_quarter":
        return _quarter_start(today), today
    if period == "this_year":
        return today.replace(month=1, day=1), today
    return None, None


def normalize_advanced_report_filters(query_params, entreprise):
    today = timezone.localdate()
    period = (query_params.get("period") or "this_month").strip()
    if period not in {choice[0] for choice in PERIOD_CHOICES}:
        period = "this_month"

    preset_start, preset_end = _period_dates(period, today)
    raw_start = (query_params.get("date_debut") or "").strip()
    raw_end = (query_params.get("date_fin") or "").strip()
    date_debut = parse_date(raw_start) if raw_start else preset_start
    date_fin = parse_date(raw_end) if raw_end else preset_end
    if date_debut and date_fin and date_debut > date_fin:
        date_debut, date_fin = date_fin, date_debut

    currency = (query_params.get("devise") or "").strip().upper()
    if not currency:
        currency = get_currency_code(entreprise)

    caisse = None
    raw_caisse = (query_params.get("caisse") or "").strip()
    if raw_caisse:
        try:
            caisse_id = int(raw_caisse)
        except (TypeError, ValueError):
            caisse_id = None
        if caisse_id:
            caisse = get_report_caisses(entreprise).filter(id=caisse_id).first()

    invoice_status = (query_params.get("statut_facture") or "").strip()
    if invoice_status not in {choice[0] for choice in INVOICE_STATUS_CHOICES}:
        invoice_status = ""
    payment_status = (query_params.get("statut_paiement") or "").strip()
    if payment_status not in {choice[0] for choice in PAYMENT_STATUS_CHOICES}:
        payment_status = ""
    payment_method = (query_params.get("moyen_paiement") or "").strip()
    if payment_method not in {choice[0] for choice in PAYMENT_METHOD_CHOICES}:
        payment_method = ""

    days = (date_fin - date_debut).days if date_debut and date_fin else 0
    group_by = "month" if period == "this_year" or days > 92 else "day"
    return {
        "period": period,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "currency": currency,
        "caisse": caisse,
        "invoice_status": invoice_status,
        "payment_status": payment_status,
        "payment_method": payment_method,
        "group_by": group_by,
        "raw": {
            "period": period,
            "date_debut": date_debut.isoformat() if date_debut else "",
            "date_fin": date_fin.isoformat() if date_fin else "",
            "devise": currency,
            "caisse": caisse.id if caisse else "",
            "statut_facture": invoice_status,
            "statut_paiement": payment_status,
            "moyen_paiement": payment_method,
        },
    }


def _selector_filters(filters):
    return {
        "date_debut": filters.get("date_debut"),
        "date_fin": filters.get("date_fin"),
        "currency": filters.get("currency"),
        "caisse": filters.get("caisse"),
        "invoice_status": filters.get("invoice_status"),
        "payment_status": filters.get("payment_status"),
        "payment_method": filters.get("payment_method"),
        "group_by": filters.get("group_by"),
    }


def build_advanced_report_payload(entreprise, filters):
    selector_filters = _selector_filters(filters)
    financial = get_financial_summary(entreprise, selector_filters)
    sales = get_sales_analysis(entreprise, selector_filters)
    payments = get_payment_analysis(entreprise, selector_filters)
    cash = get_cash_analysis(entreprise, selector_filters)
    stock = get_stock_analysis(entreprise, selector_filters)
    expenses = get_expense_analysis(entreprise, selector_filters)
    accounting = get_accounting_analysis(entreprise, selector_filters)
    management = get_management_indicators(financial, payments, stock, accounting)
    return {
        "financial": financial,
        "sales": sales,
        "payments": payments,
        "cash": cash,
        "stock": stock,
        "expenses": expenses,
        "accounting": accounting,
        "management": management,
    }


def _money(entreprise, value):
    return format_amount_for_entreprise(value, entreprise)


def _percent(value):
    return f"{format_decimal_number(value, decimal_places=2)}%"


def _decorate_amount_rows(entreprise, rows, keys=("total",)):
    for row in rows:
        for key in keys:
            if key in row:
                row[f"{key}_display"] = _money(entreprise, row[key])
    return rows


def _decorate_chart_rows(entreprise, rows):
    max_total = max([abs(row["total"]) for row in rows] or [0])
    for row in rows:
        row["total_display"] = _money(entreprise, row["total"])
        row["percent"] = int((abs(row["total"]) / max_total) * 100) if max_total else 0
    return rows


def _invoice_rows(entreprise, invoices):
    return [
        {
            "numero": invoice.numero,
            "client": invoice.client_display,
            "date": invoice.date.strftime("%d/%m/%Y"),
            "status": invoice.get_statut_display(),
            "amount_display": _money(entreprise, invoice.montant),
        }
        for invoice in invoices
    ]


def _expense_rows(entreprise, expenses):
    return [
        {
            "description": expense.description,
            "date": expense.date.strftime("%d/%m/%Y"),
            "amount_display": _money(entreprise, expense.montant),
        }
        for expense in expenses
    ]


def _stock_product_rows(entreprise, products, status_label=""):
    return [
        {
            "name": product.nom,
            "reference": product.reference,
            "quantity": product.quantite_stock,
            "threshold": product.seuil_alerte,
            "status": status_label,
            "value_display": _money(entreprise, product.quantite_stock * product.prix_unitaire),
        }
        for product in products
    ]


def decorate_advanced_report_payload(entreprise, report):
    financial = report["financial"]
    report["financial_cards"] = [
        {"label": "Chiffre d'affaires", "value": _money(entreprise, financial["revenue_total"])},
        {"label": "Encaisse", "value": _money(entreprise, financial["collected_total"])},
        {"label": "Reste a encaisser", "value": _money(entreprise, financial["remaining_total"])},
        {"label": "Depenses", "value": _money(entreprise, financial["expenses_total"])},
        {"label": "Solde net", "value": _money(entreprise, financial["net_balance"])},
        {"label": "Factures", "value": financial["invoice_count"]},
        {"label": "Factures payees", "value": financial["paid_invoice_count"]},
        {"label": "Paiements en attente", "value": financial["pending_payment_count"]},
        {"label": "Caisse disponible", "value": _money(entreprise, financial["cash_available_total"])},
    ]
    report["management_cards"] = [
        {"label": "Taux de paiement", "value": _percent(report["management"]["payment_rate"])},
        {"label": "Taux d'impayes", "value": _percent(report["management"]["unpaid_rate"])},
        {"label": "Resultat simplifie", "value": _money(entreprise, report["management"]["simplified_margin"])},
        {"label": "Variation stock", "value": report["management"]["stock_variation"]},
    ]

    report["sales"]["evolution"] = _decorate_chart_rows(entreprise, report["sales"]["evolution"])
    report["sales"]["top_clients"] = _decorate_amount_rows(entreprise, report["sales"]["top_clients"])
    report["sales"]["top_items"] = _decorate_amount_rows(entreprise, report["sales"]["top_items"])
    report["sales"]["recent_invoice_rows"] = _invoice_rows(entreprise, report["sales"]["recent_invoices"])
    report["sales"]["unpaid_invoice_rows"] = _invoice_rows(entreprise, report["sales"]["unpaid_invoices"])
    report["sales"]["partial_invoice_rows"] = _invoice_rows(entreprise, report["sales"]["partial_invoices"])

    report["payments"]["method_breakdown"] = _decorate_amount_rows(
        entreprise,
        report["payments"]["method_breakdown"],
        keys=("total", "confirmed_total"),
    )
    report["payments"]["status_breakdown"] = _decorate_amount_rows(entreprise, report["payments"]["status_breakdown"])
    report["payments"]["total_mobile_money_display"] = _money(entreprise, report["payments"]["total_mobile_money"])
    report["payments"]["total_cash_display"] = _money(entreprise, report["payments"]["total_cash"])
    report["payments"]["total_bank_display"] = _money(entreprise, report["payments"]["total_bank"])

    report["cash"]["balance_by_caisse"] = _decorate_amount_rows(
        entreprise,
        report["cash"]["balance_by_caisse"],
        keys=("total_entries", "total_exits", "balance"),
    )
    report["cash"]["total_entries_display"] = _money(entreprise, report["cash"]["total_entries"])
    report["cash"]["total_exits_display"] = _money(entreprise, report["cash"]["total_exits"])

    report["stock"]["stock_value_display"] = _money(entreprise, report["stock"]["stock_value"])
    report["stock"]["low_stock_product_rows"] = _stock_product_rows(
        entreprise,
        report["stock"]["low_stock_products"],
        "Stock faible",
    )
    report["stock"]["out_of_stock_product_rows"] = _stock_product_rows(
        entreprise,
        report["stock"]["out_of_stock_products"],
        "Rupture",
    )
    report["stock"]["alert_product_rows"] = (
        report["stock"]["low_stock_product_rows"] + report["stock"]["out_of_stock_product_rows"]
    )

    report["expenses"]["evolution"] = _decorate_chart_rows(entreprise, report["expenses"]["evolution"])
    report["expenses"]["categories"] = _decorate_amount_rows(entreprise, report["expenses"]["categories"])
    report["expenses"]["top_expense_rows"] = _expense_rows(entreprise, report["expenses"]["top_expenses"])
    report["expenses"]["total_display"] = _money(entreprise, report["expenses"]["total"])

    report["accounting"]["products_total_display"] = _money(entreprise, report["accounting"]["products_total"])
    report["accounting"]["charges_total_display"] = _money(entreprise, report["accounting"]["charges_total"])
    report["accounting"]["result_display"] = _money(entreprise, report["accounting"]["result"])
    return report


def build_advanced_report_context(entreprise, filters):
    report = decorate_advanced_report_payload(entreprise, build_advanced_report_payload(entreprise, filters))
    return {
        "entreprise": entreprise,
        "report": report,
        "filters": filters["raw"],
        "period_choices": PERIOD_CHOICES,
        "invoice_status_choices": INVOICE_STATUS_CHOICES,
        "payment_status_choices": PAYMENT_STATUS_CHOICES,
        "payment_method_choices": PAYMENT_METHOD_CHOICES,
        "currency_choices": get_available_report_currencies(entreprise),
        "caisses": get_report_caisses(entreprise),
        "currency_code": filters.get("currency") or get_currency_code(entreprise),
    }


def build_advanced_report_export_rows(entreprise, report):
    financial = report["financial"]
    payments = report["payments"]
    stock = report["stock"]
    cash = report["cash"]
    expenses = report["expenses"]
    management = report["management"]
    return [
        ["Synthese", "Chiffre d'affaires", financial["revenue_total"], ""],
        ["Synthese", "Encaissements", financial["collected_total"], ""],
        ["Synthese", "Reste a encaisser", financial["remaining_total"], ""],
        ["Synthese", "Depenses", financial["expenses_total"], ""],
        ["Synthese", "Solde net", financial["net_balance"], ""],
        ["Factures", "Nombre total", financial["invoice_count"], ""],
        ["Factures", "Payees", financial["paid_invoice_count"], ""],
        ["Factures", "Impayees", financial["unpaid_invoice_count"], ""],
        ["Paiements", "Confirmes", payments["confirmed_count"], ""],
        ["Paiements", "En attente", payments["pending_count"], ""],
        ["Paiements", "Rejetes", payments["rejected_count"], ""],
        ["Paiements", "Annules", payments["cancelled_count"], ""],
        ["Paiements", "Total Mobile Money", payments["total_mobile_money"], ""],
        ["Paiements", "Total cash", payments["total_cash"], ""],
        ["Paiements", "Total banque", payments["total_bank"], ""],
        ["Caisse", "Entrees", cash["total_entries"], ""],
        ["Caisse", "Sorties", cash["total_exits"], ""],
        ["Stock", "Valeur estimee", stock["stock_value"], ""],
        ["Stock", "Produits stock faible", stock["low_stock_count"], ""],
        ["Stock", "Produits en rupture", stock["out_of_stock_count"], ""],
        ["Depenses", "Total", expenses["total"], ""],
        ["Gestion", "Taux de paiement", management["payment_rate"], "%"],
        ["Gestion", "Taux d'impayes", management["unpaid_rate"], "%"],
        ["Gestion", "Resultat simplifie", management["simplified_margin"], ""],
    ]
