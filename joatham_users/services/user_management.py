from django.contrib.auth import get_user_model
from django.db import transaction

from core.audit import record_audit_event


User = get_user_model()


ALLOWED_MANAGED_ROLES = {
    User.Role.GESTIONNAIRE,
    User.Role.COMPTABLE,
}


def _split_full_name(full_name):
    full_name = (full_name or "").strip()
    if not full_name:
        return "", ""
    parts = full_name.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _ensure_manageable_role(role):
    if role not in ALLOWED_MANAGED_ROLES:
        raise ValueError("Le proprietaire peut creer uniquement un gestionnaire ou un comptable.")


def _ensure_email_available(email, *, exclude_user_id=None):
    normalized_email = (email or "").strip().lower()
    email_qs = User.objects.filter(email__iexact=normalized_email)
    username_qs = User.objects.filter(username__iexact=normalized_email)
    if exclude_user_id:
        email_qs = email_qs.exclude(id=exclude_user_id)
        username_qs = username_qs.exclude(id=exclude_user_id)
    if email_qs.exists() or username_qs.exists():
        raise ValueError("Un compte existe deja avec cet email.")
    return normalized_email


@transaction.atomic
def create_company_user(*, entreprise, owner_user, full_name, email, telephone, role, password):
    _ensure_manageable_role(role)
    normalized_email = _ensure_email_available(email)
    first_name, last_name = _split_full_name(full_name)
    user = User.objects.create_user(
        username=normalized_email,
        email=normalized_email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        telephone=(telephone or "").strip(),
        role=role,
        entreprise=entreprise,
        is_active=True,
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=owner_user,
        action="utilisateur_cree",
        module="users",
        objet_type="User",
        objet_id=user.id,
        description=f"Utilisateur {normalized_email} cree avec le role {role}.",
        metadata={"role": role, "email": normalized_email},
    )
    return user


@transaction.atomic
def update_company_user(*, target_user, owner_user, full_name, email, telephone, role, password=""):
    if target_user.normalized_role == User.Role.PROPRIETAIRE:
        raise ValueError("Le compte proprietaire ne peut pas etre modifie depuis cette interface.")

    _ensure_manageable_role(role)
    normalized_email = _ensure_email_available(email, exclude_user_id=target_user.id)
    first_name, last_name = _split_full_name(full_name)

    target_user.first_name = first_name
    target_user.last_name = last_name
    target_user.email = normalized_email
    target_user.username = normalized_email
    target_user.telephone = (telephone or "").strip()
    target_user.role = role
    if password:
        target_user.set_password(password)
    target_user.save()

    record_audit_event(
        entreprise=target_user.entreprise,
        utilisateur=owner_user,
        action="utilisateur_modifie",
        module="users",
        objet_type="User",
        objet_id=target_user.id,
        description=f"Utilisateur {normalized_email} modifie.",
        metadata={"role": role, "email": normalized_email},
    )
    return target_user


@transaction.atomic
def toggle_company_user_active(*, target_user, owner_user):
    if target_user.normalized_role == User.Role.PROPRIETAIRE:
        raise ValueError("Le compte proprietaire ne peut pas etre desactive.")

    target_user.is_active = not target_user.is_active
    target_user.save(update_fields=["is_active"])
    record_audit_event(
        entreprise=target_user.entreprise,
        utilisateur=owner_user,
        action="utilisateur_statut_modifie",
        module="users",
        objet_type="User",
        objet_id=target_user.id,
        description=f"Statut utilisateur mis a jour pour {target_user.email or target_user.username}.",
        metadata={"is_active": target_user.is_active},
    )
    return target_user


@transaction.atomic
def delete_company_user(*, target_user, owner_user):
    if target_user.normalized_role == User.Role.PROPRIETAIRE:
        raise ValueError("Le compte proprietaire ne peut pas etre supprime.")
    if target_user.id == owner_user.id:
        raise ValueError("Vous ne pouvez pas supprimer votre propre compte.")

    user_id = target_user.id
    email = target_user.email or target_user.username
    entreprise = target_user.entreprise
    target_user.delete()
    record_audit_event(
        entreprise=entreprise,
        utilisateur=owner_user,
        action="utilisateur_supprime",
        module="users",
        objet_type="User",
        objet_id=user_id,
        description=f"Utilisateur {email} supprime.",
        metadata={"email": email},
    )
