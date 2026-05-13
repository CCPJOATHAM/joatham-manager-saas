from decimal import Decimal

from django.db.models import Count, Q, Sum

from core.services.tenancy import get_object_for_entreprise, scope_queryset_to_entreprise

from ..models import PaymentTransaction


def _coalesce_amount(value):
    return value if value is not None else Decimal("0.00")


def get_payment_transaction_queryset():
    return PaymentTransaction.objects.select_related(
        "entreprise",
        "created_by",
        "validated_by",
        "cancelled_by",
        "facture",
        "paiement_facture",
        "depense",
        "caisse",
        "session_caisse",
        "mouvement_caisse",
    )


def get_payment_transactions_for_entreprise(
    entreprise,
    *,
    status=None,
    method=None,
    transaction_type=None,
    facture=None,
    caisse=None,
    session_caisse=None,
    date_debut=None,
    date_fin=None,
    q=None,
):
    queryset = scope_queryset_to_entreprise(get_payment_transaction_queryset(), entreprise)
    if status:
        queryset = queryset.filter(status=status)
    if method:
        queryset = queryset.filter(method=method)
    if transaction_type:
        queryset = queryset.filter(transaction_type=transaction_type)
    if facture is not None:
        queryset = queryset.filter(facture=facture)
    if caisse is not None:
        queryset = queryset.filter(caisse=caisse)
    if session_caisse is not None:
        queryset = queryset.filter(session_caisse=session_caisse)
    if date_debut:
        queryset = queryset.filter(transaction_date__date__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(transaction_date__date__lte=date_fin)
    if q:
        queryset = queryset.filter(
            Q(reference__icontains=q)
            | Q(note__icontains=q)
            | Q(phone_number__icontains=q)
            | Q(facture__numero__icontains=q)
            | Q(depense__description__icontains=q)
        )
    return queryset.order_by("-transaction_date", "-id")


def get_payment_transaction_for_entreprise(entreprise, transaction_id):
    return get_object_for_entreprise(get_payment_transaction_queryset(), entreprise, id=transaction_id)


def get_payment_summary(entreprise, *, queryset=None):
    payments = queryset if queryset is not None else get_payment_transactions_for_entreprise(entreprise)
    totals = payments.aggregate(
        total_encaisse=Sum(
            "amount",
            filter=Q(
                status=PaymentTransaction.Status.CONFIRME,
                transaction_type=PaymentTransaction.TransactionType.ENCAISSEMENT,
            ),
        ),
        total_en_attente=Sum("amount", filter=Q(status=PaymentTransaction.Status.EN_ATTENTE)),
        total_rejete=Sum("amount", filter=Q(status=PaymentTransaction.Status.REJETE)),
        total_annule=Sum("amount", filter=Q(status=PaymentTransaction.Status.ANNULE)),
        nombre=Count("id"),
    )
    return {
        "total_encaisse": _coalesce_amount(totals.get("total_encaisse")),
        "total_en_attente": _coalesce_amount(totals.get("total_en_attente")),
        "total_rejete": _coalesce_amount(totals.get("total_rejete")),
        "total_annule": _coalesce_amount(totals.get("total_annule")),
        "nombre": totals.get("nombre") or 0,
    }


def get_payment_method_breakdown(entreprise, *, queryset=None):
    payments = queryset if queryset is not None else get_payment_transactions_for_entreprise(entreprise)
    labels = dict(PaymentTransaction.Method.choices)
    return [
        {
            "method": row["method"],
            "label": labels.get(row["method"], row["method"]),
            "count": row["count"],
            "total": _coalesce_amount(row["total"]),
        }
        for row in payments.values("method").annotate(count=Count("id"), total=Sum("amount")).order_by("method")
    ]


def get_payment_status_breakdown(entreprise, *, queryset=None):
    payments = queryset if queryset is not None else get_payment_transactions_for_entreprise(entreprise)
    labels = dict(PaymentTransaction.Status.choices)
    return [
        {
            "status": row["status"],
            "label": labels.get(row["status"], row["status"]),
            "count": row["count"],
            "total": _coalesce_amount(row["total"]),
        }
        for row in payments.values("status").annotate(count=Count("id"), total=Sum("amount")).order_by("status")
    ]

