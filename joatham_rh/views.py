from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.permissions import permission_required, user_has_permission

from .forms import EmployeForm, PosteForm, PresenceForm
from .models import Employe, Presence
from .selectors.rh import (
    get_employe_by_entreprise,
    get_employes_by_entreprise,
    get_postes_by_entreprise,
    get_presences_by_entreprise,
)
from .services.rh import RhOperationError, create_employe, create_poste, record_presence, update_employe


def _build_rh_ui_permissions(user):
    return {
        "can_manage_rh_ui": user_has_permission(user, "rh.manage"),
        "can_record_presence_ui": user_has_permission(user, "rh.presence"),
    }


def _build_status_label(status):
    return {
        Employe.Statut.ACTIF: _("Actif"),
        Employe.Statut.SUSPENDU: _("Suspendu"),
        Employe.Statut.SORTI: _("Sorti"),
    }.get(status, status)


def _build_presence_status_label(status):
    return {
        Presence.Statut.PRESENT: _("Present"),
        Presence.Statut.ABSENT: _("Absent"),
        Presence.Statut.RETARD: _("Retard"),
        Presence.Statut.CONGE: _("Conge"),
    }.get(status, status)


@permission_required("rh.view")
@module_access_required("rh")
def employe_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    employes = get_employes_by_entreprise(entreprise)
    rows = [
        {
            "instance": employe,
            "status_label": _build_status_label(employe.statut),
        }
        for employe in employes
    ]
    return render(
        request,
        "joatham_rh/employe_list.html",
        {
            "employes": rows,
            "employe_count": len(rows),
            **_build_rh_ui_permissions(request.user),
        },
    )


@permission_required("rh.view")
@module_access_required("rh")
def employe_detail(request, employe_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    employe = get_employe_by_entreprise(entreprise, employe_id)
    presences = Presence.objects.filter(entreprise=entreprise, employe=employe).order_by("-date", "-id")[:20]
    return render(
        request,
        "joatham_rh/employe_detail.html",
        {
            "employe": employe,
            "status_label": _build_status_label(employe.statut),
            "presences": [
                {
                    "instance": presence,
                    "status_label": _build_presence_status_label(presence.statut),
                }
                for presence in presences
            ],
            **_build_rh_ui_permissions(request.user),
        },
    )


@permission_required("rh.manage")
@module_access_required("rh")
def employe_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = EmployeForm(request.POST or None, entreprise=entreprise)
    if request.method == "POST" and form.is_valid():
        try:
            employe = create_employe(
                entreprise=entreprise,
                utilisateur=request.user,
                **form.cleaned_data,
            )
        except RhOperationError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, _("L'employe a ete cree avec succes."))
            return redirect("rh_employe_detail", employe_id=employe.id)

    return render(
        request,
        "joatham_rh/employe_form.html",
        {
            "form": form,
            "page_title": _("Nouvel employe"),
            "submit_label": _("Creer l'employe"),
            "is_create_mode": True,
            **_build_rh_ui_permissions(request.user),
        },
    )


@permission_required("rh.manage")
@module_access_required("rh")
def employe_update(request, employe_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    employe = get_employe_by_entreprise(entreprise, employe_id)
    form = EmployeForm(request.POST or None, instance=employe, entreprise=entreprise)
    if request.method == "POST" and form.is_valid():
        try:
            employe = update_employe(
                entreprise=entreprise,
                employe=employe,
                utilisateur=request.user,
                **form.cleaned_data,
            )
        except RhOperationError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, _("L'employe a ete mis a jour avec succes."))
            return redirect("rh_employe_detail", employe_id=employe.id)

    return render(
        request,
        "joatham_rh/employe_form.html",
        {
            "form": form,
            "page_title": _("Modifier un employe"),
            "submit_label": _("Enregistrer"),
            "employe": employe,
            "is_create_mode": False,
            **_build_rh_ui_permissions(request.user),
        },
    )


@permission_required("rh.view")
@module_access_required("rh")
def poste_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    postes = get_postes_by_entreprise(entreprise)
    return render(
        request,
        "joatham_rh/poste_list.html",
        {
            "postes": postes,
            "poste_count": postes.count(),
            **_build_rh_ui_permissions(request.user),
        },
    )


@permission_required("rh.manage")
@module_access_required("rh")
def poste_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = PosteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_poste(
                entreprise=entreprise,
                utilisateur=request.user,
                **form.cleaned_data,
            )
        except RhOperationError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, _("Le poste a ete cree avec succes."))
            return redirect("rh_poste_list")

    return render(
        request,
        "joatham_rh/poste_form.html",
        {
            "form": form,
            "page_title": _("Nouveau poste"),
            "submit_label": _("Creer le poste"),
            **_build_rh_ui_permissions(request.user),
        },
    )


@permission_required("rh.view")
@module_access_required("rh")
def presence_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    presences = [
        {
            "instance": presence,
            "status_label": _build_presence_status_label(presence.statut),
        }
        for presence in get_presences_by_entreprise(entreprise)
    ]
    return render(
        request,
        "joatham_rh/presence_list.html",
        {
            "presences": presences,
            "presence_count": len(presences),
            **_build_rh_ui_permissions(request.user),
        },
    )


@permission_required("rh.presence")
@module_access_required("rh")
def presence_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = PresenceForm(request.POST or None, entreprise=entreprise)
    if request.method == "POST" and form.is_valid():
        try:
            record_presence(
                entreprise=entreprise,
                utilisateur=request.user,
                **form.cleaned_data,
            )
        except RhOperationError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, _("La presence a ete enregistree avec succes."))
            return redirect("rh_presence_list")

    return render(
        request,
        "joatham_rh/presence_form.html",
        {
            "form": form,
            "page_title": _("Nouvelle presence"),
            "submit_label": _("Enregistrer la presence"),
            **_build_rh_ui_permissions(request.user),
        },
    )
