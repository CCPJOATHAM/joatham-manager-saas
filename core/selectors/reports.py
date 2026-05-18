from decimal import Decimal

from django.utils import timezone
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth

from core.services.currency import get_currency_code
from joatham_billing.models import Facture, LigneFacture, PaiementFacture
from joatham_caisse.models import Caisse, MouvementCaisse, SessionCaisse
from joatham_caisse.selectors.mouvements import get_cash_flow_totals_for_session, get_mouvements_for_entreprise
from joatham_caisse.selectors.session import get_sessions_by_entreprise
from joatham_clients.models import Client
from joatham_comptabilite.services.reporting import build_compte_resultat
from joatham_depenses.models import Depense
from joatham_payments.models import PaymentTransaction
from joatham_products.models import InventoryLine, InventorySession, Produit, StockMovement
from joatham_products.selectors.inventory import get_inventory_sessions_for_entreprise
from joatham_products.selectors.stock import get_stock_movements_for_entreprise


ZERO = Decimal("0.00")

ENTRY_CASH_TYPES = [
    MouvementCaisse.TypeMouvement.ENTREE,
    MouvementCaisse.TypeMouvement.PAIEMENT_FACTURE,
    MouvementCaisse.TypeMouvement.AJUSTEMENT,
]
EXIT_CASH_TYPES = [
    MouvementCaisse.TypeMouvement.SORTIE,
    MouvementCaisse.TypeMouvement.DEPENSE,
    MouvementCaisse.TypeMouvement.TRANSFERT,
]
ENTRY_STOCK_TYPES = {
    StockMovement.MovementType.MANUAL_ENTRY,
    StockMovement.MovementType.INVOICE_RESTORE,
    StockMovement.MovementType.ADJUSTMENT_POSITIVE,
    StockMovement.MovementType.TRANSFER_IN,
}
EXIT_STOCK_TYPES = {
    StockMovement.MovementType.MANUAL_EXIT,
    StockMovement.MovementType.INVOICE_SALE,
    StockMovement.MovementType.ADJUSTMENT_NEGATIVE,
    StockMovement.MovementType.TRANSFER_OUT,
}

PAYMENT_METHODS = [
    {"code": "cash", "label": "Cash"},
    {"code": "mpesa", "label": "M-Pesa"},
    {"code": "orange_money", "label": "Orange Money"},
    {"code": "airtel_money", "label": "Airtel Money"},
    {"code": "afrimoney", "label": "Afrimoney"},
    {"code": "mobile_money", "label": "Mobile Money"},
    {"code": "bank", "label": "Banque"},
    {"code": "card", "label": "Carte"},
    {"code": "other", "label": "Autre"},
]
PAYMENT_METHOD_VARIANTS = {
    "cash": {"cash", "especes"},
    "mpesa": {"mpesa"},
    "orange_money": {"orange_money"},
    "airtel_money": {"airtel_money"},
    "afrimoney": {"afrimoney"},
    "mobile_money": {"mobile_money"},
    "bank": {"bank", "bank_transfer", "virement"},
    "card": {"card", "carte"},
    "other": {"other", "autre", "cheque"},
}
PAYMENT_STATUS_MAP = {
    "confirme": {
        "transaction": {PaymentTransaction.Status.CONFIRME},
        "invoice": {PaiementFacture.StatutPaiement.VALIDE},
    },
    "valide": {
        "transaction": {PaymentTransaction.Status.CONFIRME},
        "invoice": {PaiementFacture.StatutPaiement.VALIDE},
    },
    "en_attente": {
        "transaction": {PaymentTransaction.Status.EN_ATTENTE},
        "invoice": {PaiementFacture.StatutPaiement.EN_ATTENTE},
    },
    "rejete": {
        "transaction": {PaymentTransaction.Status.REJETE},
        "invoice": set(),
    },
    "annule": {
        "transaction": {PaymentTransaction.Status.ANNULE},
        "invoice": {PaiementFacture.StatutPaiement.ANNULE},
    },
}
PAYMENT_STATUS_LABELS = {
    "confirme": "Confirmes",
    "en_attente": "En attente",
    "rejete": "Rejetes",
    "annule": "Annules",
}
MOBILE_MONEY_METHOD_CODES = {"mpesa", "orange_money", "airtel_money", "afrimoney", "mobile_money"}


def _coalesce_amount(value):
    return value if value is not None else ZERO


def _company_currency_matches(entreprise, currency):
    return not currency or currency == get_currency_code(entreprise)


def _method_variants(method):
    if not method:
        return set()
    return PAYMENT_METHOD_VARIANTS.get(method, {method})


def _normalize_method(method):
    if not method:
        return "other"
    for normalized, variants in PAYMENT_METHOD_VARIANTS.items():
        if method in variants:
            return normalized
    return method if method in {item["code"] for item in PAYMENT_METHODS} else "other"


def _apply_currency_filter(queryset, currency, field_name):
    if currency:
        return queryset.filter(**{field_name: currency})
    return queryset


def _apply_method_filter(queryset, method, field_name):
    variants = _method_variants(method)
    if variants:
        return queryset.filter(**{f"{field_name}__in": variants})
    return queryset


def _apply_transaction_status_filter(queryset, status):
    statuses = PAYMENT_STATUS_MAP.get(status, {}).get("transaction")
    if statuses is not None:
        if not statuses:
            return queryset.none()
        return queryset.filter(status__in=statuses)
    return queryset


def _apply_invoice_payment_status_filter(queryset, status):
    statuses = PAYMENT_STATUS_MAP.get(status, {}).get("invoice")
    if statuses is not None:
        if not statuses:
            return queryset.none()
        return queryset.filter(statut__in=statuses)
    return queryset


def get_available_report_currencies(entreprise):
    currencies = {get_currency_code(entreprise)}
    currencies.update(
        PaymentTransaction.objects.filter(entreprise=entreprise)
        .exclude(currency="")
        .values_list("currency", flat=True)
        .distinct()
    )
    currencies.update(
        Caisse.objects.filter(entreprise=entreprise)
        .exclude(devise="")
        .values_list("devise", flat=True)
        .distinct()
    )
    return sorted({(currency or "").strip().upper() for currency in currencies if currency})


def get_report_caisses(entreprise):
    return Caisse.objects.filter(entreprise=entreprise).order_by("nom", "id")


def get_report_clients(entreprise):
    return Client.objects.filter(entreprise=entreprise).order_by("nom", "id")


def get_advanced_invoice_queryset(entreprise, *, date_debut=None, date_fin=None, invoice_status=None, currency=None):
    queryset = Facture.objects.filter(entreprise=entreprise).select_related("client").order_by("-date", "-id")
    if not _company_currency_matches(entreprise, currency):
        return queryset.none()
    if invoice_status == "impaye":
        queryset = queryset.exclude(statut=Facture.Statut.ANNULEE).filter(paye=False)
    elif invoice_status == "partielle":
        queryset = queryset.exclude(statut=Facture.Statut.ANNULEE).filter(
            paye=False,
            paiements__statut=PaiementFacture.StatutPaiement.VALIDE,
        ).distinct()
    elif invoice_status in dict(Facture.Statut.choices):
        queryset = queryset.filter(statut=invoice_status)
    if date_debut:
        queryset = queryset.filter(date__date__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(date__date__lte=date_fin)
    return queryset


def get_advanced_invoice_payments_queryset(
    entreprise,
    *,
    date_debut=None,
    date_fin=None,
    caisse=None,
    payment_method=None,
    payment_status=None,
    currency=None,
):
    queryset = PaiementFacture.objects.filter(entreprise=entreprise).select_related("facture", "caisse", "session_caisse")
    if not _company_currency_matches(entreprise, currency):
        return queryset.none()
    if date_debut:
        queryset = queryset.filter(date_paiement__date__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(date_paiement__date__lte=date_fin)
    if caisse is not None:
        queryset = queryset.filter(caisse=caisse)
    queryset = _apply_method_filter(queryset, payment_method, "mode")
    queryset = _apply_invoice_payment_status_filter(queryset, payment_status)
    return queryset.order_by("-date_paiement", "-id")


def get_advanced_payment_transactions_queryset(
    entreprise,
    *,
    date_debut=None,
    date_fin=None,
    caisse=None,
    payment_method=None,
    payment_status=None,
    currency=None,
):
    queryset = PaymentTransaction.objects.filter(entreprise=entreprise).select_related(
        "facture",
        "paiement_facture",
        "depense",
        "caisse",
        "session_caisse",
    )
    if date_debut:
        queryset = queryset.filter(transaction_date__date__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(transaction_date__date__lte=date_fin)
    if caisse is not None:
        queryset = queryset.filter(caisse=caisse)
    queryset = _apply_currency_filter(queryset, currency, "currency")
    queryset = _apply_method_filter(queryset, payment_method, "method")
    queryset = _apply_transaction_status_filter(queryset, payment_status)
    return queryset.order_by("-transaction_date", "-id")


def get_advanced_expenses_queryset(entreprise, *, date_debut=None, date_fin=None, caisse=None, currency=None):
    queryset = Depense.objects.filter(entreprise=entreprise).select_related("caisse", "session_caisse").order_by("-date", "-id")
    if not _company_currency_matches(entreprise, currency):
        return queryset.none()
    if date_debut:
        queryset = queryset.filter(date__date__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(date__date__lte=date_fin)
    if caisse is not None:
        queryset = queryset.filter(caisse=caisse)
    return queryset


def _iter_invoices_with_totals(queryset):
    if hasattr(queryset, "prefetch_related"):
        return queryset.prefetch_related("lignes", "paiements")
    return queryset


def _sum_invoice_amounts(queryset):
    total = ZERO
    for facture in _iter_invoices_with_totals(queryset):
        total += Decimal(facture.total_net or 0)
    return total


def _get_collected_amount(entreprise, filters):
    invoice_payments = get_advanced_invoice_payments_queryset(entreprise, **filters).filter(
        statut=PaiementFacture.StatutPaiement.VALIDE
    )
    standalone_transactions = (
        get_advanced_payment_transactions_queryset(entreprise, **filters)
        .filter(
            status=PaymentTransaction.Status.CONFIRME,
            transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
        )
        .filter(paiement_facture__isnull=True)
    )
    return _coalesce_amount(invoice_payments.aggregate(total=Sum("montant")).get("total")) + _coalesce_amount(
        standalone_transactions.aggregate(total=Sum("amount")).get("total")
    )


def _get_invoice_remaining_amount(entreprise, invoices, currency=None):
    if not _company_currency_matches(entreprise, currency):
        return ZERO
    payments_total = _coalesce_amount(
        PaiementFacture.objects.filter(
            entreprise=entreprise,
            facture__in=invoices,
            statut=PaiementFacture.StatutPaiement.VALIDE,
        ).aggregate(total=Sum("montant")).get("total")
    )
    remaining = _sum_invoice_amounts(invoices) - payments_total
    return remaining if remaining > ZERO else ZERO


def get_financial_summary(entreprise, filters):
    invoice_filters = {
        "date_debut": filters.get("date_debut"),
        "date_fin": filters.get("date_fin"),
        "invoice_status": filters.get("invoice_status"),
        "currency": filters.get("currency"),
    }
    payment_filters = {
        "date_debut": filters.get("date_debut"),
        "date_fin": filters.get("date_fin"),
        "caisse": filters.get("caisse"),
        "payment_method": filters.get("payment_method"),
        "payment_status": filters.get("payment_status"),
        "currency": filters.get("currency"),
    }
    invoices = get_advanced_invoice_queryset(entreprise, **invoice_filters)
    active_invoices = invoices.exclude(statut=Facture.Statut.ANNULEE)
    expenses = get_advanced_expenses_queryset(
        entreprise,
        date_debut=filters.get("date_debut"),
        date_fin=filters.get("date_fin"),
        caisse=filters.get("caisse"),
        currency=filters.get("currency"),
    )
    invoice_payments = get_advanced_invoice_payments_queryset(entreprise, **payment_filters)
    transactions = get_advanced_payment_transactions_queryset(entreprise, **payment_filters)
    pending_count = invoice_payments.filter(statut=PaiementFacture.StatutPaiement.EN_ATTENTE).count() + transactions.filter(
        status=PaymentTransaction.Status.EN_ATTENTE
    ).count()
    revenue_total = _sum_invoice_amounts(active_invoices)
    collected_total = _get_collected_amount(entreprise, payment_filters)
    expenses_total = _coalesce_amount(expenses.aggregate(total=Sum("montant")).get("total"))
    cash_available = get_cash_available_total(
        entreprise,
        caisse=filters.get("caisse"),
        currency=filters.get("currency"),
    )

    return {
        "revenue_total": revenue_total,
        "collected_total": collected_total,
        "remaining_total": _get_invoice_remaining_amount(entreprise, active_invoices, currency=filters.get("currency")),
        "expenses_total": expenses_total,
        "net_balance": collected_total - expenses_total,
        "invoice_count": invoices.count(),
        "paid_invoice_count": active_invoices.filter(Q(paye=True) | Q(statut=Facture.Statut.PAYEE)).count(),
        "unpaid_invoice_count": active_invoices.filter(paye=False).count(),
        "partial_invoice_count": active_invoices.filter(
            paye=False,
            paiements__statut=PaiementFacture.StatutPaiement.VALIDE,
        ).distinct().count(),
        "pending_payment_count": pending_count,
        "cash_available_total": cash_available,
    }


def get_sales_analysis(entreprise, filters):
    invoices = get_advanced_invoice_queryset(
        entreprise,
        date_debut=filters.get("date_debut"),
        date_fin=filters.get("date_fin"),
        invoice_status=filters.get("invoice_status"),
        currency=filters.get("currency"),
    )
    active_invoices = invoices.exclude(statut=Facture.Statut.ANNULEE)
    group_by_month = filters.get("group_by") == "month"
    period_buckets = {}
    client_buckets = {}
    for facture in _iter_invoices_with_totals(active_invoices.select_related("client")):
        invoice_date = timezone.localtime(facture.date) if timezone.is_aware(facture.date) else facture.date
        period = invoice_date.replace(day=1).date() if group_by_month else invoice_date.date()
        period_bucket = period_buckets.setdefault(period, {"period": period, "total": ZERO, "count": 0})
        period_bucket["total"] += Decimal(facture.total_net or 0)
        period_bucket["count"] += 1

        client_name = facture.client.nom if facture.client_id else facture.client_nom
        client_key = (facture.client_id, client_name or "Client non renseigne")
        client_bucket = client_buckets.setdefault(
            client_key,
            {"client_id": facture.client_id, "name": client_key[1], "total": ZERO, "count": 0},
        )
        client_bucket["total"] += Decimal(facture.total_net or 0)
        client_bucket["count"] += 1

    evolution = [
        {
            "period": row["period"],
            "label": row["period"].strftime("%m/%Y" if group_by_month else "%d/%m"),
            "total": row["total"],
            "count": row["count"],
        }
        for row in sorted(period_buckets.values(), key=lambda item: item["period"])
    ]
    top_clients = sorted(client_buckets.values(), key=lambda item: (-item["total"], item["name"]))[:8]
    line_amount = ExpressionWrapper(F("quantite") * F("prix_unitaire"), output_field=DecimalField(max_digits=14, decimal_places=2))
    top_items = [
        {
            "name": row["produit__nom"] or row["service__nom"] or row["designation"],
            "quantity": row["quantity"] or 0,
            "total": _coalesce_amount(row["total"]),
            "count": row["count"],
        }
        for row in LigneFacture.objects.filter(facture__in=active_invoices)
        .values("produit__nom", "service__nom", "designation")
        .annotate(quantity=Sum("quantite"), total=Sum(line_amount), count=Count("id"))
        .order_by("-total", "designation")[:8]
    ]
    partial_invoices = active_invoices.filter(
        paye=False,
        paiements__statut=PaiementFacture.StatutPaiement.VALIDE,
    ).distinct()
    return {
        "evolution": evolution,
        "top_clients": top_clients,
        "top_items": top_items,
        "recent_invoices": list(invoices[:8]),
        "unpaid_invoices": list(active_invoices.filter(paye=False)[:8]),
        "partial_invoices": list(partial_invoices[:8]),
    }


def _add_breakdown_amount(breakdown, method, *, amount, count=1, confirmed=False):
    code = _normalize_method(method)
    bucket = breakdown.setdefault(code, {"code": code, "label": code, "count": 0, "total": ZERO, "confirmed_total": ZERO})
    bucket["count"] += count
    bucket["total"] += _coalesce_amount(amount)
    if confirmed:
        bucket["confirmed_total"] += _coalesce_amount(amount)


def _add_status_amount(breakdown, status, *, amount, count=1):
    bucket = breakdown.setdefault(
        status,
        {"code": status, "label": PAYMENT_STATUS_LABELS.get(status, status), "count": 0, "total": ZERO},
    )
    bucket["count"] += count
    bucket["total"] += _coalesce_amount(amount)


def get_payment_analysis(entreprise, filters):
    payment_filters = {
        "date_debut": filters.get("date_debut"),
        "date_fin": filters.get("date_fin"),
        "caisse": filters.get("caisse"),
        "payment_method": filters.get("payment_method"),
        "payment_status": filters.get("payment_status"),
        "currency": filters.get("currency"),
    }
    invoice_payments = get_advanced_invoice_payments_queryset(entreprise, **payment_filters)
    transactions = get_advanced_payment_transactions_queryset(entreprise, **payment_filters)

    method_breakdown = {
        item["code"]: {"code": item["code"], "label": item["label"], "count": 0, "total": ZERO, "confirmed_total": ZERO}
        for item in PAYMENT_METHODS
    }
    status_breakdown = {
        code: {"code": code, "label": label, "count": 0, "total": ZERO}
        for code, label in PAYMENT_STATUS_LABELS.items()
    }

    for row in transactions.values("method", "status").annotate(count=Count("id"), total=Sum("amount")):
        status = row["status"]
        normalized_status = "confirme" if status == PaymentTransaction.Status.CONFIRME else status
        _add_breakdown_amount(
            method_breakdown,
            row["method"],
            amount=row["total"],
            count=row["count"],
            confirmed=status == PaymentTransaction.Status.CONFIRME,
        )
        _add_status_amount(status_breakdown, normalized_status, amount=row["total"], count=row["count"])

    orphan_invoice_payments = invoice_payments.filter(payment_transaction__isnull=True)
    for row in orphan_invoice_payments.values("mode", "statut").annotate(count=Count("id"), total=Sum("montant")):
        normalized_status = {
            PaiementFacture.StatutPaiement.VALIDE: "confirme",
            PaiementFacture.StatutPaiement.EN_ATTENTE: "en_attente",
            PaiementFacture.StatutPaiement.ANNULE: "annule",
        }.get(row["statut"], row["statut"])
        _add_breakdown_amount(
            method_breakdown,
            row["mode"],
            amount=row["total"],
            count=row["count"],
            confirmed=row["statut"] == PaiementFacture.StatutPaiement.VALIDE,
        )
        _add_status_amount(status_breakdown, normalized_status, amount=row["total"], count=row["count"])

    methods = list(method_breakdown.values())
    mobile_total = sum((row["confirmed_total"] for row in methods if row["code"] in MOBILE_MONEY_METHOD_CODES), ZERO)
    cash_total = method_breakdown["cash"]["confirmed_total"]
    bank_total = method_breakdown["bank"]["confirmed_total"]
    return {
        "method_breakdown": methods,
        "status_breakdown": list(status_breakdown.values()),
        "confirmed_count": status_breakdown["confirme"]["count"],
        "pending_count": status_breakdown["en_attente"]["count"],
        "rejected_count": status_breakdown["rejete"]["count"],
        "cancelled_count": status_breakdown["annule"]["count"],
        "total_mobile_money": mobile_total,
        "total_cash": cash_total,
        "total_bank": bank_total,
        "recent_payments": list(transactions[:8]),
        "recent_invoice_payments": list(orphan_invoice_payments[:8]),
    }


def get_cash_available_total(entreprise, *, caisse=None, currency=None):
    sessions = SessionCaisse.objects.filter(entreprise=entreprise, statut=SessionCaisse.Statut.OUVERTE).select_related("caisse")
    if caisse is not None:
        sessions = sessions.filter(caisse=caisse)
    if currency:
        sessions = sessions.filter(caisse__devise=currency)
    total = ZERO
    for session in sessions:
        totals = get_cash_flow_totals_for_session(session)
        total += Decimal(str(session.solde_initial or 0))
        total += Decimal(str(totals["total_entrees"] or 0))
        total -= Decimal(str(totals["total_sorties"] or 0))
    return total


def get_cash_analysis(entreprise, filters):
    movements = get_mouvements_for_entreprise(
        entreprise,
        caisse=filters.get("caisse"),
        date_debut=filters.get("date_debut"),
        date_fin=filters.get("date_fin"),
    ).filter(statut=MouvementCaisse.Statut.CONFIRME)
    if filters.get("payment_method"):
        movements = movements.filter(moyen_paiement__in=_method_variants(filters["payment_method"]))
    if filters.get("currency"):
        movements = movements.filter(devise=filters["currency"])
    sessions = get_sessions_by_entreprise(
        entreprise,
        caisse=filters.get("caisse"),
        date_debut=filters.get("date_debut"),
        date_fin=filters.get("date_fin"),
    )
    if filters.get("currency"):
        sessions = sessions.filter(caisse__devise=filters["currency"])
    totals = movements.aggregate(
        total_entries=Sum("montant", filter=Q(type_mouvement__in=ENTRY_CASH_TYPES)),
        total_exits=Sum("montant", filter=Q(type_mouvement__in=EXIT_CASH_TYPES)),
        movement_count=Count("id"),
    )
    by_caisse = []
    for row in movements.values("caisse_id", "caisse__nom", "caisse__code", "caisse__devise").annotate(
        total_entries=Sum("montant", filter=Q(type_mouvement__in=ENTRY_CASH_TYPES)),
        total_exits=Sum("montant", filter=Q(type_mouvement__in=EXIT_CASH_TYPES)),
        count=Count("id"),
    ).order_by("caisse__nom", "caisse_id"):
        entries = _coalesce_amount(row["total_entries"])
        exits = _coalesce_amount(row["total_exits"])
        by_caisse.append(
            {
                "caisse_id": row["caisse_id"],
                "name": row["caisse__nom"],
                "code": row["caisse__code"],
                "currency": row["caisse__devise"],
                "total_entries": entries,
                "total_exits": exits,
                "balance": entries - exits,
                "count": row["count"],
            }
        )
    return {
        "total_entries": _coalesce_amount(totals["total_entries"]),
        "total_exits": _coalesce_amount(totals["total_exits"]),
        "movement_count": totals["movement_count"] or 0,
        "balance_by_caisse": by_caisse,
        "recent_movements": list(movements[:8]),
        "open_sessions": sessions.filter(statut=SessionCaisse.Statut.OUVERTE).count(),
        "closed_sessions": sessions.filter(statut=SessionCaisse.Statut.FERMEE).count(),
        "validated_sessions": sessions.filter(statut=SessionCaisse.Statut.VALIDEE).count(),
        "sessions_with_gap": sessions.exclude(ecart=0).count(),
    }


def get_stock_analysis(entreprise, filters):
    products = Produit.objects.filter(entreprise=entreprise, actif=True).order_by("nom", "id")
    stock_value = ZERO
    if _company_currency_matches(entreprise, filters.get("currency")):
        product_value = ExpressionWrapper(
            F("quantite_stock") * F("prix_unitaire"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        stock_value = _coalesce_amount(products.aggregate(total=Sum(product_value)).get("total"))
    low_stock = products.filter(quantite_stock__gt=0, quantite_stock__lte=F("seuil_alerte"))
    out_of_stock = products.filter(quantite_stock__lte=0)
    movements = get_stock_movements_for_entreprise(
        entreprise,
        date_debut=filters.get("date_debut"),
        date_fin=filters.get("date_fin"),
    )
    movement_totals = movements.aggregate(
        entries=Sum("quantity", filter=Q(movement_type__in=ENTRY_STOCK_TYPES)),
        exits=Sum("quantity", filter=Q(movement_type__in=EXIT_STOCK_TYPES)),
        count=Count("id"),
    )
    inventory_sessions = get_inventory_sessions_for_entreprise(
        entreprise,
        date_debut=filters.get("date_debut"),
        date_fin=filters.get("date_fin"),
    )
    validated_ids = list(inventory_sessions.filter(status=InventorySession.Status.VALIDATED).values_list("id", flat=True))
    inventory_lines = InventoryLine.objects.filter(entreprise=entreprise, session_id__in=validated_ids)
    inventory_gaps = inventory_lines.exclude(difference=0).count()
    entries = movement_totals["entries"] or 0
    exits = movement_totals["exits"] or 0
    return {
        "stock_value": stock_value,
        "low_stock_count": low_stock.count(),
        "out_of_stock_count": out_of_stock.count(),
        "low_stock_products": list(low_stock[:8]),
        "out_of_stock_products": list(out_of_stock[:8]),
        "recent_movements": list(movements[:8]),
        "latest_inventories": list(inventory_sessions[:5]),
        "inventory_gap_count": inventory_gaps,
        "movement_entries": entries,
        "movement_exits": exits,
        "stock_variation": entries - exits,
    }


def _has_expense_category():
    try:
        Depense._meta.get_field("categorie")
    except Exception:
        return False
    return True


def get_expense_analysis(entreprise, filters):
    expenses = get_advanced_expenses_queryset(
        entreprise,
        date_debut=filters.get("date_debut"),
        date_fin=filters.get("date_fin"),
        caisse=filters.get("caisse"),
        currency=filters.get("currency"),
    )
    group_function = TruncMonth if filters.get("group_by") == "month" else TruncDay
    evolution = [
        {
            "period": row["period"],
            "label": row["period"].strftime("%m/%Y" if filters.get("group_by") == "month" else "%d/%m"),
            "total": _coalesce_amount(row["total"]),
            "count": row["count"],
        }
        for row in expenses.annotate(period=group_function("date"))
        .values("period")
        .annotate(total=Sum("montant"), count=Count("id"))
        .order_by("period")
    ]
    categories = []
    if _has_expense_category():
        categories = [
            {
                "category": row["categorie"] or "Sans categorie",
                "total": _coalesce_amount(row["total"]),
                "count": row["count"],
            }
            for row in expenses.values("categorie").annotate(total=Sum("montant"), count=Count("id")).order_by("-total")
        ]
    return {
        "total": _coalesce_amount(expenses.aggregate(total=Sum("montant")).get("total")),
        "count": expenses.count(),
        "evolution": evolution,
        "categories": categories,
        "top_expenses": list(expenses.order_by("-montant", "-date")[:8]),
    }


def get_accounting_analysis(entreprise, filters):
    try:
        result = build_compte_resultat(
            entreprise,
            date_debut=filters.get("date_debut"),
            date_fin=filters.get("date_fin"),
        )
    except Exception:
        return {
            "available": False,
            "products_total": ZERO,
            "charges_total": ZERO,
            "result": ZERO,
            "result_label": "Indisponible",
        }
    return {
        "available": True,
        "products_total": result["total_produits"],
        "charges_total": result["total_charges"],
        "result": result["resultat_net"],
        "result_label": result["resultat_label"],
    }


def get_management_indicators(financial, payment, stock, accounting):
    invoice_count = financial["invoice_count"] or 0
    payment_rate = (financial["paid_invoice_count"] / invoice_count * 100) if invoice_count else 0
    unpaid_rate = (financial["unpaid_invoice_count"] / invoice_count * 100) if invoice_count else 0
    return {
        "payment_rate": round(payment_rate, 2),
        "unpaid_rate": round(unpaid_rate, 2),
        "simplified_margin": financial["net_balance"],
        "accounting_result": accounting["result"] if accounting.get("available") else ZERO,
        "stock_variation": stock["stock_variation"],
        "recent_activity_count": (
            financial["invoice_count"]
            + payment["confirmed_count"]
            + payment["pending_count"]
            + stock["movement_entries"]
            + stock["movement_exits"]
        ),
    }
