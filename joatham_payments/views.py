from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date

from core.services.currency import format_amount_for_entreprise
from core.services.product_policy import can_access_module, module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_apprenants.services.export_service import build_report_metadata, build_xlsx_response
from joatham_billing.models import Facture
from joatham_billing.pdf import render_pdf_response
from joatham_caisse.models import Caisse, SessionCaisse
from joatham_users.permissions import permission_required, user_has_permission

from .forms import PaymentDecisionForm, PaymentTransactionForm
from .models import PaymentTransaction
from .selectors.payments import (
    get_payment_method_breakdown,
    get_payment_status_breakdown,
    get_payment_summary,
    get_payment_transaction_for_entreprise,
    get_payment_transactions_for_entreprise,
)
from .services.payments import (
    PaymentOperationError,
    cancel_payment_transaction,
    confirm_payment_transaction,
    create_payment_transaction,
    reject_payment_transaction,
)


def _resolve_id(model, entreprise, raw_value):
    if not raw_value:
        return None
    try:
        object_id = int(raw_value)
    except (TypeError, ValueError):
        return None
    return model.objects.filter(id=object_id, entreprise=entreprise).first()


def _get_filters_from_request(request, entreprise):
    raw_date_debut = request.GET.get("date_debut", "")
    raw_date_fin = request.GET.get("date_fin", "")
    status = (request.GET.get("status") or "").strip()
    method = (request.GET.get("method") or "").strip()
    transaction_type = (request.GET.get("transaction_type") or "").strip()
    q = (request.GET.get("q") or "").strip()
    facture = _resolve_id(Facture, entreprise, request.GET.get("facture"))
    caisse = _resolve_id(Caisse, entreprise, request.GET.get("caisse"))
    session_caisse = _resolve_id(SessionCaisse, entreprise, request.GET.get("session_caisse"))
    return {
        "status": status,
        "method": method,
        "transaction_type": transaction_type,
        "facture": facture,
        "caisse": caisse,
        "session_caisse": session_caisse,
        "date_debut": parse_date(raw_date_debut or ""),
        "date_fin": parse_date(raw_date_fin or ""),
        "q": q,
        "raw": {
            "status": status,
            "method": method,
            "transaction_type": transaction_type,
            "facture": facture.id if facture else "",
            "caisse": caisse.id if caisse else "",
            "session_caisse": session_caisse.id if session_caisse else "",
            "date_debut": raw_date_debut,
            "date_fin": raw_date_fin,
            "q": q,
        },
        "query_string": request.GET.urlencode(),
    }


def _get_filtered_payments(request, entreprise):
    filters = _get_filters_from_request(request, entreprise)
    payments = get_payment_transactions_for_entreprise(
        entreprise,
        status=filters["status"] or None,
        method=filters["method"] or None,
        transaction_type=filters["transaction_type"] or None,
        facture=filters["facture"],
        caisse=filters["caisse"],
        session_caisse=filters["session_caisse"],
        date_debut=filters["date_debut"],
        date_fin=filters["date_fin"],
        q=filters["q"],
    )
    return payments, filters


def _payment_context_flags(user):
    can_view_reports = user_has_permission(user, "payments.view") and can_access_module(user, "payments_reports")
    can_export = user_has_permission(user, "payments.export") and can_access_module(user, "payments_exports")
    return {
        "can_create_payment": user_has_permission(user, "payments.create"),
        "can_validate_payment": user_has_permission(user, "payments.validate"),
        "can_cancel_payment": user_has_permission(user, "payments.cancel"),
        "can_view_payment_reports": can_view_reports,
        "can_export_payments": can_export,
    }


@permission_required("payments.view")
@module_access_required("payments")
def payment_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    payments, filters = _get_filtered_payments(request, entreprise)
    return render(
        request,
        "joatham_payments/payment_list.html",
        {
            "payments": payments[:200],
            "summary": get_payment_summary(entreprise, queryset=payments),
            "method_breakdown": get_payment_method_breakdown(entreprise, queryset=payments),
            "status_choices": PaymentTransaction.Status.choices,
            "method_choices": PaymentTransaction.Method.choices,
            "transaction_type_choices": PaymentTransaction.TransactionType.choices,
            "factures": Facture.objects.filter(entreprise=entreprise).order_by("-date", "-id")[:100],
            "caisses": Caisse.objects.filter(entreprise=entreprise, est_active=True).order_by("nom"),
            "sessions": SessionCaisse.objects.filter(entreprise=entreprise).select_related("caisse").order_by("-date_ouverture")[:100],
            "filters": filters["raw"],
            "filter_query": filters["query_string"],
            **_payment_context_flags(request.user),
        },
    )


@permission_required("payments.create")
@module_access_required("payments")
def payment_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = PaymentTransactionForm(
        request.POST or None,
        request.FILES or None,
        entreprise=entreprise,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        status = (
            PaymentTransaction.Status.CONFIRME
            if form.cleaned_data.get("confirm_now")
            else PaymentTransaction.Status.EN_ATTENTE
        )
        try:
            payment = create_payment_transaction(
                entreprise=entreprise,
                transaction_type=form.cleaned_data["transaction_type"],
                method=form.cleaned_data["method"],
                amount=form.cleaned_data["amount"],
                currency=form.cleaned_data["currency"],
                reference=form.cleaned_data["reference"],
                phone_number=form.cleaned_data["phone_number"],
                mobile_operator=form.cleaned_data["mobile_operator"],
                status=status,
                transaction_date=form.cleaned_data["transaction_date"],
                facture=form.cleaned_data["facture"],
                depense=form.cleaned_data["depense"],
                caisse=form.cleaned_data["caisse"],
                session_caisse=form.cleaned_data["session_caisse"],
                note=form.cleaned_data["note"],
                attachment=form.cleaned_data.get("attachment"),
                utilisateur=request.user,
            )
        except (PaymentOperationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Le paiement a ete enregistre.")
            return redirect("payment_detail", payment_id=payment.id)

    return render(
        request,
        "joatham_payments/payment_form.html",
        {
            "form": form,
            "page_title": "Nouveau paiement",
            "submit_label": "Enregistrer le paiement",
            **_payment_context_flags(request.user),
        },
    )


@permission_required("payments.view")
@module_access_required("payments")
def payment_detail(request, payment_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    payment = get_payment_transaction_for_entreprise(entreprise, payment_id)
    return render(
        request,
        "joatham_payments/payment_detail.html",
        {
            "payment": payment,
            "decision_form": PaymentDecisionForm(),
            "amount_display": format_amount_for_entreprise(payment.amount, entreprise),
            **_payment_context_flags(request.user),
        },
    )


@login_required
@permission_required("payments.validate")
@module_access_required("payment_validation")
def payment_confirm(request, payment_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    payment = get_payment_transaction_for_entreprise(entreprise, payment_id)
    if request.method == "POST":
        try:
            confirm_payment_transaction(transaction_obj=payment, utilisateur=request.user)
        except (PaymentOperationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Le paiement a ete confirme.")
    return redirect("payment_detail", payment_id=payment.id)


@login_required
@permission_required("payments.validate")
@module_access_required("payment_validation")
def payment_reject(request, payment_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    payment = get_payment_transaction_for_entreprise(entreprise, payment_id)
    form = PaymentDecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            reject_payment_transaction(
                transaction_obj=payment,
                utilisateur=request.user,
                note=form.cleaned_data["note"],
            )
        except (PaymentOperationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Le paiement a ete rejete.")
    return redirect("payment_detail", payment_id=payment.id)


@login_required
@permission_required("payments.cancel")
@module_access_required("payment_validation")
def payment_cancel(request, payment_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    payment = get_payment_transaction_for_entreprise(entreprise, payment_id)
    form = PaymentDecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            cancel_payment_transaction(
                transaction_obj=payment,
                utilisateur=request.user,
                note=form.cleaned_data["note"],
            )
        except (PaymentOperationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Le paiement a ete annule.")
    return redirect("payment_detail", payment_id=payment.id)


@permission_required("payments.view")
@module_access_required("payments_reports")
def payment_reports(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    payments, filters = _get_filtered_payments(request, entreprise)
    return render(
        request,
        "joatham_payments/reports.html",
        {
            "summary": get_payment_summary(entreprise, queryset=payments),
            "method_breakdown": get_payment_method_breakdown(entreprise, queryset=payments),
            "status_breakdown": get_payment_status_breakdown(entreprise, queryset=payments),
            "recent_payments": payments[:20],
            "status_choices": PaymentTransaction.Status.choices,
            "method_choices": PaymentTransaction.Method.choices,
            "transaction_type_choices": PaymentTransaction.TransactionType.choices,
            "filters": filters["raw"],
            "filter_query": filters["query_string"],
            **_payment_context_flags(request.user),
        },
    )


@permission_required("payments.export")
@module_access_required("payments_exports")
def payment_export_excel(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    payments, _filters = _get_filtered_payments(request, entreprise)
    rows = [
        [
            payment.transaction_date.strftime("%d/%m/%Y %H:%M"),
            payment.get_transaction_type_display(),
            payment.get_method_display(),
            payment.get_status_display(),
            payment.amount,
            payment.currency,
            payment.reference,
            payment.phone_number,
            payment.get_mobile_operator_display() if payment.mobile_operator else "",
            payment.facture.numero if payment.facture else "",
            payment.caisse.nom if payment.caisse else "",
            str(payment.created_by or "-"),
            str(payment.validated_by or "-"),
        ]
        for payment in payments
    ]
    return build_xlsx_response(
        filename="paiements.xlsx",
        sheet_name="Paiements",
        headers=[
            "Date",
            "Type",
            "Moyen",
            "Statut",
            "Montant",
            "Devise",
            "Reference",
            "Telephone",
            "Operateur",
            "Facture",
            "Caisse",
            "Cree par",
            "Valide par",
        ],
        rows=rows,
    )


@permission_required("payments.export")
@module_access_required("payments_exports")
def payment_reports_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    payments, filters = _get_filtered_payments(request, entreprise)
    return render_pdf_response(
        request,
        "joatham_payments/reports_pdf.html",
        {
            "summary": get_payment_summary(entreprise, queryset=payments),
            "method_breakdown": get_payment_method_breakdown(entreprise, queryset=payments),
            "status_breakdown": get_payment_status_breakdown(entreprise, queryset=payments),
            "recent_payments": payments[:40],
            "filters": filters["raw"],
            **build_report_metadata(entreprise=entreprise, title="Rapport paiements"),
        },
        filename="rapport-paiements.pdf",
        disposition="attachment",
    )
