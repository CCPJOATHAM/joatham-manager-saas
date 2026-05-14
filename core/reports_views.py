from django.shortcuts import render

from core.services.product_policy import can_access_module, module_access_required
from core.services.reports import (
    build_advanced_report_context,
    build_advanced_report_export_rows,
    build_advanced_report_payload,
    normalize_advanced_report_filters,
)
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_apprenants.services.export_service import build_report_metadata, build_xlsx_response
from joatham_billing.pdf import render_pdf_response
from joatham_users.permissions import permission_required, user_has_permission


def _build_filters(request, entreprise):
    return normalize_advanced_report_filters(request.GET, entreprise)


def _can_export(user):
    return user_has_permission(user, "reports.export") and can_access_module(user, "advanced_reports_exports")


@permission_required("reports.advanced_view")
@module_access_required("advanced_reports")
def advanced_reports(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    filters = _build_filters(request, entreprise)
    context = build_advanced_report_context(entreprise, filters)
    context.update(
        {
            "filter_query": request.GET.urlencode(),
            "can_export_advanced_reports": _can_export(request.user),
        }
    )
    return render(request, "core/advanced_reports.html", context)


advanced_reports_dashboard = advanced_reports


@permission_required("reports.export")
@module_access_required("advanced_reports_exports")
def advanced_reports_export_excel(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    filters = _build_filters(request, entreprise)
    report = build_advanced_report_payload(entreprise, filters)
    return build_xlsx_response(
        filename="rapport-avance.xlsx",
        sheet_name="Rapport avance",
        headers=["Section", "Indicateur", "Valeur", "Note"],
        rows=build_advanced_report_export_rows(entreprise, report),
    )


@permission_required("reports.export")
@module_access_required("advanced_reports_exports")
def advanced_reports_export_pdf(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    filters = _build_filters(request, entreprise)
    context = build_advanced_report_context(entreprise, filters)
    context.update(build_report_metadata(entreprise=entreprise, title="Rapport avance"))
    return render_pdf_response(
        request,
        "core/advanced_reports_pdf.html",
        context,
        filename="rapport-avance.pdf",
        disposition="attachment",
    )
