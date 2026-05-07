from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from core.services.language import persist_language_preference
from core.services.product_policy import module_access_required
from core.services.tenancy import get_user_entreprise_or_raise
from core.ui_text import FLASH_MESSAGES
from joatham_users.permissions import permission_required

from .forms import ProfileUpdateForm, UserManagementForm
from .selectors.users import get_users_by_entreprise
from .services.user_management import (
    create_company_user,
    delete_company_user,
    toggle_company_user_active,
    update_company_user,
)


def _build_user_metrics(users):
    user_list = list(users)
    return {
        "total_users": len(user_list),
        "active_users": sum(1 for user in user_list if user.is_active),
        "inactive_users": sum(1 for user in user_list if not user.is_active),
        "gestionnaire_count": sum(1 for user in user_list if user.normalized_role == "gestionnaire"),
        "comptable_count": sum(1 for user in user_list if user.normalized_role == "comptable"),
        "proprietaire_count": sum(1 for user in user_list if user.normalized_role == "proprietaire"),
    }


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
            }
        )
    return rows


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


@permission_required("users.manage")
@module_access_required("users")
def user_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    users = get_users_by_entreprise(entreprise)
    user_rows = _build_user_rows(users)
    user_metrics = _build_user_metrics(users)
    return render(
        request,
        "joatham_users/user_list.html",
        {
            "users": user_rows,
            **user_metrics,
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


@permission_required("users.manage")
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


@permission_required("users.manage")
@module_access_required("users")
def user_delete(request, user_id):
    entreprise = get_user_entreprise_or_raise(request.user)
    target_user = get_object_or_404(get_users_by_entreprise(entreprise), id=user_id)
    if request.method == "POST":
        try:
            delete_company_user(target_user=target_user, owner_user=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, FLASH_MESSAGES["user_deleted"])
    return redirect("user_list")
