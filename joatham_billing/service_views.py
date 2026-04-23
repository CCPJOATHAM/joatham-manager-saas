from django.contrib import messages
from django.shortcuts import redirect, render

from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.permissions import permission_required, require_permission, user_has_permission

from .forms_services import ServiceForm
from .selectors.billing import get_service_by_entreprise
from .services.service_catalog import create_service_for_entreprise, list_services_for_entreprise, toggle_service_active, update_service_for_entreprise


def _get_services_ui_permissions(user):
    return {
        "can_manage_services_ui": user_has_permission(user, "services.manage"),
    }


@permission_required("services.view")
@module_access_required("services")
def service_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    services = list_services_for_entreprise(entreprise)
    return render(
        request,
        "joatham_billing/service_list.html",
        {
            "services": services,
            "service_count": services.count(),
            "active_count": services.filter(actif=True).count(),
            "inactive_count": services.filter(actif=False).count(),
            **_get_services_ui_permissions(request.user),
        },
    )


@permission_required("services.manage")
@module_access_required("services")
def service_create(request):
    form = ServiceForm(request.POST or None)
    entreprise = get_user_entreprise_or_raise(request.user)

    if request.method == "POST" and form.is_valid():
        create_service_for_entreprise(
            entreprise=entreprise,
            utilisateur=request.user,
            **form.cleaned_data,
        )
        messages.success(request, "Le service a été créé avec succès.")
        return redirect("service_list")

    return render(
        request,
        "joatham_billing/service_form.html",
        {
            "form": form,
            "page_title": "Créer un service",
            "submit_label": "Créer le service",
            **_get_services_ui_permissions(request.user),
        },
    )


@permission_required("services.view")
@module_access_required("services")
def service_update(request, service_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    service = get_service_by_entreprise(entreprise, service_id)
    require_permission(request.user, "services.manage")
    form = ServiceForm(request.POST or None, instance=service)

    if request.method == "POST" and form.is_valid():
        update_service_for_entreprise(
            entreprise=entreprise,
            service_id=service.id,
            utilisateur=request.user,
            **form.cleaned_data,
        )
        messages.success(request, "Le service a été mis à jour avec succès.")
        return redirect("service_list")

    return render(
        request,
        "joatham_billing/service_form.html",
        {
            "form": form,
            "page_title": "Modifier un service",
            "submit_label": "Enregistrer les modifications",
            "service": service,
            **_get_services_ui_permissions(request.user),
        },
    )


@permission_required("services.manage")
@module_access_required("services")
def service_toggle_status(request, service_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    if request.method == "POST":
        service = toggle_service_active(
            entreprise=entreprise,
            service_id=service_id,
            utilisateur=request.user,
        )
        status_label = "activé" if service.actif else "désactivé"
        messages.success(request, f"Le service a été {status_label}.")
    return redirect("service_list")
