from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from core.services.language import persist_language_preference
from core.services.product_policy import module_access_required
from core.services.quotas import PlanQuotaExceeded, get_plan_quota_limit
from core.services.tenancy import get_user_entreprise_or_raise
from core.ui_text import FLASH_MESSAGES
from joatham_users.models import EntrepriseInvitation
from joatham_users.permissions import get_default_dashboard_name, permission_required

from .forms import InvitationAcceptanceForm, ProfileUpdateForm, UserInviteForm, UserManagementForm
from .selectors.users import (
    get_active_company_invitations,
    get_company_invitation_by_id,
    get_company_user_metrics,
    get_users_by_entreprise,
)
from .services.invitations import (
    InvitationEmailError,
    accept_company_invitation,
    cancel_company_invitation,
    get_company_invitation_role,
    parse_company_invitation_source,
    resend_company_invitation,
    create_company_invitation,
)
from .services.user_management import (
    USER_DELETE_DEACTIVATED_FOR_HISTORY,
    create_company_user,
    delete_company_user,
    remove_company_user_access,
    toggle_company_user_active,
    update_company_user,
)


User = get_user_model()

ROLE_FILTER_CHOICES = [
    ("", _("Tous les roles")),
    (User.Role.PROPRIETAIRE, _("Proprietaire")),
    (User.Role.GESTIONNAIRE, _("Gestionnaire")),
    (User.Role.COMPTABLE, _("Comptable")),
]

STATUS_FILTER_CHOICES = [
    ("", _("Tous les statuts")),
    ("active", _("Actifs")),
    ("inactive", _("Inactifs")),
]


def _build_user_rows(users):
    rows = []
    for managed_user in users:
        full_name = f"{managed_user.first_name} {managed_user.last_name}".strip() or managed_user.username
        rows.append(
            {
                "instance": managed_user,
                "full_name": full_name,
                "email_display": managed_user.email or managed_user.username,
                "telephone_display": managed_user.telephone or "-",
                "is_owner": managed_user.normalized_role == "proprietaire",
                "email_verified": managed_user.email_verified,
                "created_display": managed_user.date_joined,
                "last_login_display": managed_user.last_login,
            }
        )
    return rows


def _build_invitation_rows(invitations):
    role_labels = dict(User.Role.choices)
    rows = []
    for invitation in invitations:
        role = get_company_invitation_role(invitation)
        rows.append(
            {
                "instance": invitation,
                "role": role,
                "role_label": role_labels.get(role, role),
                "email_display": invitation.email,
                "full_name": invitation.full_name or invitation.email,
                "created_display": invitation.created_at,
                "expires_display": invitation.expires_at,
            }
        )
    return rows


def _get_invitation_or_404(entreprise, invitation_id):
    try:
        return get_company_invitation_by_id(entreprise, invitation_id)
    except EntrepriseInvitation.DoesNotExist as exc:
        raise Http404("Invitation introuvable") from exc


@login_required(login_url="login")
def profile_view(request):
    form = ProfileUpdateForm(
        request.POST or None,
        request.FILES or None,
        instance=request.user,
    )

    if request.method == "POST" and form.is_valid():
        user = form.save()
        persist_language_preference(request, user.preferred_language)
        messages.success(request, _("Votre profil a ete mis a jour."))
        return redirect("profile")

    return render(
        request,
        "joatham_users/profile.html",
        {
            "form": form,
            "profile_user": request.user,
        },
    )


@permission_required("users.view")
@module_access_required("users")
def user_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    selected_role = request.GET.get("role", "").strip()
    selected_status = request.GET.get("status", "").strip()
    search_query = request.GET.get("q", "").strip()
    users = get_users_by_entreprise(
        entreprise,
        role=selected_role or None,
        status=selected_status or None,
        search=search_query or None,
    )
    invitations = get_active_company_invitations(entreprise)
    user_rows = _build_user_rows(users)
    invitation_rows = _build_invitation_rows(invitations)
    all_users = list(get_users_by_entreprise(entreprise))
    user_metrics = get_company_user_metrics(entreprise, users=all_users, invitations=invitations)
    quota_limit = get_plan_quota_limit(entreprise, "max_utilisateurs", plan_field="max_utilisateurs")
    quota_used = user_metrics["total_users"] + user_metrics["pending_invitations"]
    quota_remaining = None if quota_limit is None else max(quota_limit - quota_used, 0)
    return render(
        request,
        "joatham_users/user_list.html",
        {
            "users": user_rows,
            "pending_invitations_list": invitation_rows,
            "role_filter_choices": ROLE_FILTER_CHOICES,
            "status_filter_choices": STATUS_FILTER_CHOICES,
            "selected_role": selected_role,
            "selected_status": selected_status,
            "search_query": search_query,
            "quota_limit": quota_limit,
            "quota_used": quota_used,
            "quota_remaining": quota_remaining,
            "quota_is_unlimited": quota_limit is None,
            "quota_label": _("Illimite") if quota_limit is None else quota_limit,
            **user_metrics,
        },
    )


@permission_required("users.invite")
@module_access_required("users")
def user_invite(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = UserInviteForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            create_company_invitation(
                entreprise=entreprise,
                owner_user=request.user,
                full_name=form.cleaned_data["full_name"],
                email=form.cleaned_data["email"],
                role=form.cleaned_data["role"],
            )
        except (InvitationEmailError, PlanQuotaExceeded, ValueError) as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, _("Invitation envoyee avec succes."))
            return redirect("user_list")

    return render(
        request,
        "joatham_users/invite_user.html",
        {
            "form": form,
        },
    )


@permission_required("users.manage")
@module_access_required("users")
def user_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = UserManagementForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        if not form.cleaned_data["password"]:
            form.add_error("password", _("Le mot de passe est obligatoire pour creer un utilisateur."))
        else:
            try:
                create_company_user(
                    entreprise=entreprise,
                    owner_user=request.user,
                    full_name=form.cleaned_data["full_name"],
                    email=form.cleaned_data["email"],
                    telephone=form.cleaned_data["telephone"],
                    role=form.cleaned_data["role"],
                    password=form.cleaned_data["password"],
                )
            except ValueError as exc:
                form.add_error("email", str(exc))
            else:
                messages.success(request, FLASH_MESSAGES["user_created"])
                return redirect("user_list")

    return render(
        request,
        "joatham_users/user_form.html",
        {
            "form": form,
            "page_title": _("Creer un utilisateur"),
            "submit_label": _("Creer l'utilisateur"),
            "form_mode": "create",
        },
    )


@permission_required("users.change_role")
@module_access_required("users")
def user_update(request, user_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    target_user = get_object_or_404(get_users_by_entreprise(entreprise), id=user_id)
    full_name = f"{target_user.first_name} {target_user.last_name}".strip() or target_user.username
    form = UserManagementForm(
        request.POST or None,
        initial={
            "full_name": full_name,
            "email": target_user.email,
            "telephone": target_user.telephone,
            "role": target_user.role,
        },
    )

    if request.method == "POST" and form.is_valid():
        try:
            update_company_user(
                target_user=target_user,
                owner_user=request.user,
                full_name=form.cleaned_data["full_name"],
                email=form.cleaned_data["email"],
                telephone=form.cleaned_data["telephone"],
                role=form.cleaned_data["role"],
                password=form.cleaned_data["password"],
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, FLASH_MESSAGES["user_updated"])
            return redirect("user_list")

    return render(
        request,
        "joatham_users/user_form.html",
        {
            "form": form,
            "page_title": _("Modifier un utilisateur"),
            "submit_label": _("Enregistrer les modifications"),
            "target_user": target_user,
            "form_mode": "update",
        },
    )


@permission_required("users.manage")
@module_access_required("users")
def user_toggle_active(request, user_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    target_user = get_object_or_404(get_users_by_entreprise(entreprise), id=user_id)
    if request.method == "POST":
        try:
            toggle_company_user_active(target_user=target_user, owner_user=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            status_label = _("active") if target_user.is_active else _("desactive")
            messages.success(request, _("Utilisateur %(status)s avec succes.") % {"status": status_label})
    return redirect("user_list")


@permission_required("users.remove")
@module_access_required("users")
def user_delete(request, user_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    target_user = get_object_or_404(get_users_by_entreprise(entreprise), id=user_id)
    if request.method == "POST":
        try:
            delete_result = delete_company_user(target_user=target_user, owner_user=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            if delete_result == USER_DELETE_DEACTIVATED_FOR_HISTORY:
                messages.warning(request, FLASH_MESSAGES["user_deactivated_history"])
            else:
                messages.success(request, FLASH_MESSAGES["user_deleted"])
    return redirect("user_list")


@permission_required("users.view")
@module_access_required("users")
def user_detail(request, user_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    target_user = get_object_or_404(get_users_by_entreprise(entreprise), id=user_id)
    full_name = f"{target_user.first_name} {target_user.last_name}".strip() or target_user.username
    return render(
        request,
        "joatham_users/user_detail.html",
        {
            "target_user": target_user,
            "full_name": full_name,
        },
    )


@permission_required("users.remove")
@module_access_required("users")
def user_remove_access(request, user_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    target_user = get_object_or_404(get_users_by_entreprise(entreprise), id=user_id)
    if request.method == "POST":
        try:
            remove_company_user_access(target_user=target_user, owner_user=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Acces retire avec succes."))
    return redirect("user_list")


@permission_required("users.invite")
@module_access_required("users")
def user_invitation_resend(request, invitation_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    invitation = _get_invitation_or_404(entreprise, invitation_id)
    if request.method == "POST":
        try:
            resend_company_invitation(invitation=invitation, entreprise=entreprise, owner_user=request.user)
        except (InvitationEmailError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Invitation renvoyee avec succes."))
    return redirect("user_list")


@permission_required("users.invite")
@module_access_required("users")
def user_invitation_cancel(request, invitation_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    invitation = _get_invitation_or_404(entreprise, invitation_id)
    if request.method == "POST":
        try:
            cancel_company_invitation(invitation=invitation, entreprise=entreprise, owner_user=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Invitation annulee avec succes."))
    return redirect("user_list")


def user_invitation_accept(request, token):
    invitation = get_object_or_404(EntrepriseInvitation, token=token)
    parsed = parse_company_invitation_source(invitation.source)
    invitation_is_invalid = (
        not parsed["is_company"] or parsed["cancelled"] or invitation.is_used or invitation.is_expired
    )
    form = InvitationAcceptanceForm(request.POST or None)

    if request.method == "POST" and not invitation_is_invalid and form.is_valid():
        try:
            user = accept_company_invitation(invitation=invitation, password=form.cleaned_data["password"])
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            login(request, user)
            messages.success(request, _("Votre acces a ete active."))
            return redirect(get_default_dashboard_name(user))

    return render(
        request,
        "joatham_users/accept_invitation.html",
        {
            "form": form,
            "invitation": invitation,
            "invitation_is_invalid": invitation_is_invalid,
            "role_label": dict(User.Role.choices).get(parsed["role"], parsed["role"]),
        },
        status=410 if invitation_is_invalid else 200,
    )
