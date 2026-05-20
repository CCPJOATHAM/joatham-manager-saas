from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.permissions import permission_required, user_has_permission

from .forms import DemandeCongeForm, DocumentRHForm, EmployeForm, PosteForm, PresenceForm
from .models import DemandeConge, Employe, Presence
from .selectors.rh import (
    get_conge_by_entreprise,
    get_conges_by_entreprise,
    get_documents_by_entreprise,
    get_employe_by_entreprise,
    get_employes_by_entreprise,
    get_postes_by_entreprise,
    get_presences_by_entreprise,
    get_rh_report_snapshot,
)
from .services.rh import (
    RhOperationError,
    approve_conge,
    create_conge,
    create_document_rh,
    create_employe,
    create_poste,
    record_presence,
    refuse_conge,
    update_employe,
)


def _build_rh_ui_permissions(user):
    return {
        "can_manage_rh_ui": user_has_permission(user, "rh.manage"),
        "can_record_presence_ui": user_has_permission(user, "rh.presence"),
        "can_manage_documents_ui": user_has_permission(user, "rh.documents"),
        "can_view_reports_ui": user_has_permission(user, "rh.reports"),
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


def _build_conge_status_label(status):
    return {
        DemandeConge.Statut.BROUILLON: _("Brouillon"),
        DemandeConge.Statut.EN_ATTENTE: _("En attente"),
        DemandeConge.Statut.APPROUVE: _("Approuve"),
        DemandeConge.Statut.REFUSE: _("Refuse"),
        DemandeConge.Statut.ANNULE: _("Annule"),
    }.get(status, status)


def _build_conge_type_label(type_conge):
    return {
        DemandeConge.TypeConge.ANNUEL: _("Annuel"),
        DemandeConge.TypeConge.MALADIE: _("Maladie"),
        DemandeConge.TypeConge.EXCEPTIONNEL: _("Exceptionnel"),
        DemandeConge.TypeConge.SANS_SOLDE: _("Sans solde"),
        DemandeConge.TypeConge.AUTRE: _("Autre"),
    }.get(type_conge, type_conge)


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


@permission_required("rh.view")
@module_access_required("rh")
def conge_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    conges = [
        {
            "instance": conge,
            "status_label": _build_conge_status_label(conge.statut),
            "type_label": _build_conge_type_label(conge.type_conge),
        }
        for conge in get_conges_by_entreprise(entreprise)
    ]
    return render(
        request,
        "joatham_rh/conge_list.html",
        {
            "conges": conges,
            "conge_count": len(conges),
            **_build_rh_ui_permissions(request.user),
        },
    )


@permission_required("rh.manage")
@module_access_required("rh")
def conge_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = DemandeCongeForm(request.POST or None, entreprise=entreprise)
    if request.method == "POST" and form.is_valid():
        try:
            create_conge(
                entreprise=entreprise,
                utilisateur=request.user,
                **form.cleaned_data,
            )
        except RhOperationError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, _("La demande de conge a ete creee avec succes."))
            return redirect("rh_conge_list")

    return render(
        request,
        "joatham_rh/conge_form.html",
        {
            "form": form,
            "page_title": _("Nouvelle demande de conge"),
            "submit_label": _("Creer la demande"),
            **_build_rh_ui_permissions(request.user),
        },
    )


@require_POST
@permission_required("rh.manage")
@module_access_required("rh")
def conge_approve(request, conge_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    conge = get_conge_by_entreprise(entreprise, conge_id)
    try:
        approve_conge(
            entreprise=entreprise,
            conge=conge,
            decide_par=request.user,
            commentaire_decision=request.POST.get("commentaire_decision", ""),
        )
    except RhOperationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("La demande de conge a ete approuvee."))
    return redirect("rh_conge_list")


@require_POST
@permission_required("rh.manage")
@module_access_required("rh")
def conge_refuse(request, conge_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    conge = get_conge_by_entreprise(entreprise, conge_id)
    try:
        refuse_conge(
            entreprise=entreprise,
            conge=conge,
            decide_par=request.user,
            commentaire_decision=request.POST.get("commentaire_decision", ""),
        )
    except RhOperationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("La demande de conge a ete refusee."))
    return redirect("rh_conge_list")


@permission_required("rh.documents")
@module_access_required("rh")
def document_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    documents = get_documents_by_entreprise(entreprise)
    return render(
        request,
        "joatham_rh/document_list.html",
        {
            "documents": documents,
            "document_count": documents.count(),
            **_build_rh_ui_permissions(request.user),
        },
    )


@permission_required("rh.documents")
@module_access_required("rh")
def document_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = DocumentRHForm(request.POST or None, entreprise=entreprise)
    if request.method == "POST" and form.is_valid():
        try:
            create_document_rh(
                entreprise=entreprise,
                utilisateur=request.user,
                **form.cleaned_data,
            )
        except RhOperationError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, _("Le document RH a ete enregistre avec succes."))
            return redirect("rh_document_list")

    return render(
        request,
        "joatham_rh/document_form.html",
        {
            "form": form,
            "page_title": _("Nouveau document RH"),
            "submit_label": _("Enregistrer le document"),
            **_build_rh_ui_permissions(request.user),
        },
    )


@permission_required("rh.reports")
@module_access_required("rh")
def rh_reports(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    report = get_rh_report_snapshot(entreprise)
    return render(
        request,
        "joatham_rh/reports.html",
        {
            "report": report,
            **_build_rh_ui_permissions(request.user),
        },
    )
