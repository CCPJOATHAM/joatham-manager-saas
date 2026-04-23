from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date

from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_billing.pdf import PdfRenderError, render_pdf_response
from joatham_users.permissions import permission_required

from .selectors.comptabilite import get_entreprises_for_accounting_user
from .services.reporting import build_balance, build_bilan_simplifie, build_compte_resultat, build_dashboard, build_grand_livre, build_report_payload


REPORT_TEMPLATES = {
    "balance": "joatham_comptabilite/balance.html",
    "grand_livre": "joatham_comptabilite/grand_livre.html",
    "compte_resultat": "joatham_comptabilite/resultat.html",
    "bilan": "joatham_comptabilite/bilan.html",
}


def _get_available_entreprises(user):
    entreprises = get_entreprises_for_accounting_user(user)
    if not user.is_superuser:
        get_user_entreprise_or_raise(user)
    return entreprises


def _get_selected_entreprise(request):
    entreprises = _get_available_entreprises(request.user)
    if not entreprises.exists():
        raise PermissionDenied("Aucune entreprise n'est associee a cet utilisateur.")

    requested_id = request.GET.get("entreprise")
    if requested_id:
        entreprise = entreprises.filter(pk=requested_id).first()
        if entreprise is None:
            raise Http404("Entreprise introuvable.")
        return entreprise, entreprises

    return entreprises.first(), entreprises


def _get_filters(request):
    return {
        "date_debut": parse_date(request.GET.get("date_debut") or ""),
        "date_fin": parse_date(request.GET.get("date_fin") or ""),
    }


def _build_filter_query(entreprise, filters):
    params = {}
    if entreprise:
        params["entreprise"] = entreprise.pk
    if filters["date_debut"]:
        params["date_debut"] = filters["date_debut"].isoformat()
    if filters["date_fin"]:
        params["date_fin"] = filters["date_fin"].isoformat()
    encoded = urlencode(params)
    return f"?{encoded}" if encoded else ""


def _build_shared_context(request, report_slug, report_title, entreprise, entreprises, filters):
    return {
        "report_slug": report_slug,
        "report_title": report_title,
        "selected_entreprise": entreprise,
        "entreprises": entreprises,
        "filters": filters,
        "filter_query": _build_filter_query(entreprise, filters),
    }


def _render_report(request, report_slug):
    entreprise, entreprises = _get_selected_entreprise(request)
    filters = _get_filters(request)
    payload = build_report_payload(report_slug, entreprise, **filters)
    context = _build_shared_context(
        request,
        report_slug=report_slug,
        report_title=payload["report_title"],
        entreprise=entreprise,
        entreprises=entreprises,
        filters=filters,
    )
    context.update(payload["report"])
    return render(request, REPORT_TEMPLATES[report_slug], context)


@permission_required("accounting.view")
@module_access_required("accounting")
def compte_resultat(request):
    return _render_report(request, "compte_resultat")


@permission_required("accounting.view")
@module_access_required("accounting")
def bilan(request):
    return _render_report(request, "bilan")


@permission_required("accounting.view")
@module_access_required("accounting")
def grand_livre(request):
    return _render_report(request, "grand_livre")


@permission_required("accounting.view")
@module_access_required("accounting")
def balance(request):
    return _render_report(request, "balance")


@permission_required("accounting.view")
@module_access_required("accounting")
def comptabilite_dashboard(request):
    entreprise, entreprises = _get_selected_entreprise(request)
    filters = _get_filters(request)
    dashboard = build_dashboard(entreprise, **filters)
    context = _build_shared_context(
        request,
        report_slug="dashboard",
        report_title="Tableau de bord comptable",
        entreprise=entreprise,
        entreprises=entreprises,
        filters=filters,
    )
    context.update(dashboard)
    return render(request, "joatham_comptabilite/dashboard.html", context)


@permission_required("accounting.export")
@module_access_required("accounting")
def export_report(request, report_slug, fmt):
    if report_slug not in REPORT_TEMPLATES:
        raise Http404("Rapport inconnu.")

    entreprise, entreprises = _get_selected_entreprise(request)
    filters = _get_filters(request)
    payload = build_report_payload(report_slug, entreprise, **filters)
    context = _build_shared_context(
        request,
        report_slug=report_slug,
        report_title=payload["report_title"],
        entreprise=entreprise,
        entreprises=entreprises,
        filters=filters,
    )
    context.update(payload["report"])

    filename_root = f"{report_slug}_{entreprise.nom}".replace(" ", "_").lower()

    if fmt == "pdf":
        try:
            return render_pdf_response(
                request,
                "joatham_comptabilite/exports/report_pdf.html",
                context,
                filename=f"{filename_root}.pdf",
                disposition="attachment",
            )
        except PdfRenderError:
            return HttpResponse("Erreur lors de la generation du PDF.", status=500)

    if fmt == "excel":
        html = render_to_string("joatham_comptabilite/exports/report_excel.html", context, request=request)
        response = HttpResponse(
            html,
            content_type="application/vnd.ms-excel; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename_root}.xls"'
        return response

    raise Http404("Format d'export inconnu.")
