from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from core.audit import record_audit_event
from core.services.quotas import assert_user_quota_available

from .session_security import release_active_session


User = get_user_model()


USER_DELETE_DELETED = "deleted"
USER_DELETE_DEACTIVATED_FOR_HISTORY = "deactivated_for_history"
IGNORED_DELETE_HISTORY_ACCESSORS = {"active_session"}
SELF_ACCESS_MESSAGE = "Vous ne pouvez pas modifier votre propre accès depuis cette interface."
LAST_ACTIVE_OWNER_MESSAGE = "Impossible de retirer l'accès au dernier propriétaire actif de l'entreprise."
OWNER_PROTECTED_MESSAGE = "Le compte propriétaire ne peut pas être modifié depuis cette interface."


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


def _record_blocked_user_action(*, target_user, owner_user, operation, reason, message):
    record_audit_event(
        entreprise=target_user.entreprise,
        utilisateur=owner_user,
        action="utilisateur_action_bloquee",
        module="users",
        objet_type="User",
        objet_id=target_user.id,
        description=message,
        metadata={
            "operation": operation,
            "reason": reason,
            "target_user_id": target_user.id,
            "target_email": target_user.email or target_user.username,
        },
    )


def _raise_blocked_action(*, target_user, owner_user, operation, reason, message):
    _record_blocked_user_action(
        target_user=target_user,
        owner_user=owner_user,
        operation=operation,
        reason=reason,
        message=message,
    )
    raise ValueError(message)


def _ensure_secondary_user(target_user, owner_user, operation):
    if target_user.normalized_role == User.Role.PROPRIETAIRE:
        _raise_blocked_action(
            target_user=target_user,
            owner_user=owner_user,
            operation=operation,
            reason="owner_protected",
            message=OWNER_PROTECTED_MESSAGE,
        )


def _ensure_not_self(target_user, owner_user, operation):
    if target_user.id == owner_user.id:
        _raise_blocked_action(
            target_user=target_user,
            owner_user=owner_user,
            operation=operation,
            reason="self_action",
            message=SELF_ACCESS_MESSAGE,
        )


def _ensure_not_last_active_owner(target_user, owner_user, operation):
    if target_user.normalized_role != User.Role.PROPRIETAIRE or not target_user.is_active:
        return

    active_owner_count = User.objects.filter(
        entreprise=target_user.entreprise,
        role=User.Role.PROPRIETAIRE,
        is_active=True,
    ).count()
    if active_owner_count <= 1:
        _raise_blocked_action(
            target_user=target_user,
            owner_user=owner_user,
            operation=operation,
            reason="last_active_owner",
            message=LAST_ACTIVE_OWNER_MESSAGE,
        )


def _has_related_history(target_user):
    for relation in target_user._meta.related_objects:
        accessor_name = relation.get_accessor_name()
        if not accessor_name or accessor_name in IGNORED_DELETE_HISTORY_ACCESSORS:
            continue

        try:
            related = getattr(target_user, accessor_name)
        except ObjectDoesNotExist:
            continue

        if relation.one_to_one:
            return True

        if hasattr(related, "exists") and related.exists():
            return True

        if hasattr(related, "all") and related.all().exists():
            return True

    return False


def _deactivate_user_for_history(*, target_user, owner_user, reason):
    was_active = target_user.is_active
    if was_active:
        target_user.is_active = False
        target_user.save(update_fields=["is_active"])

    release_active_session(target_user)
    record_audit_event(
        entreprise=target_user.entreprise,
        utilisateur=owner_user,
        action="utilisateur_desactive_historique",
        module="users",
        objet_type="User",
        objet_id=target_user.id,
        description=(
            f"Utilisateur {target_user.email or target_user.username} desactive afin de preserver la tracabilite."
        ),
        metadata={
            "email": target_user.email or target_user.username,
            "reason": reason,
            "was_active": was_active,
        },
    )
    return USER_DELETE_DEACTIVATED_FOR_HISTORY


@transaction.atomic
def create_company_user(*, entreprise, owner_user, full_name, email, telephone, role, password):
    _ensure_manageable_role(role)
    assert_user_quota_available(entreprise)
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


def update_company_user(*, target_user, owner_user, full_name, email, telephone, role, password=""):
    _ensure_not_self(target_user, owner_user, "update_role")
    _ensure_secondary_user(target_user, owner_user, "update_role")
    _ensure_manageable_role(role)
    normalized_email = _ensure_email_available(email, exclude_user_id=target_user.id)
    first_name, last_name = _split_full_name(full_name)

    with transaction.atomic():
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


def toggle_company_user_active(*, target_user, owner_user):
    if target_user.is_active:
        _ensure_not_self(target_user, owner_user, "toggle_active")
        _ensure_not_last_active_owner(target_user, owner_user, "toggle_active")
    _ensure_secondary_user(target_user, owner_user, "toggle_active")

    with transaction.atomic():
        target_user.is_active = not target_user.is_active
        target_user.save(update_fields=["is_active"])
        if not target_user.is_active:
            release_active_session(target_user)
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


def delete_company_user(*, target_user, owner_user):
    _ensure_not_self(target_user, owner_user, "delete")
    _ensure_not_last_active_owner(target_user, owner_user, "delete")
    _ensure_secondary_user(target_user, owner_user, "delete")

    user_id = target_user.id
    email = target_user.email or target_user.username
    entreprise = target_user.entreprise

    with transaction.atomic():
        if _has_related_history(target_user):
            return _deactivate_user_for_history(
                target_user=target_user,
                owner_user=owner_user,
                reason="related_history",
            )

        try:
            target_user.delete()
        except (ProtectedError, IntegrityError):
            return _deactivate_user_for_history(
                target_user=target_user,
                owner_user=owner_user,
                reason="protected_relation",
            )

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
    return USER_DELETE_DELETED


def remove_company_user_access(*, target_user, owner_user):
    _ensure_not_self(target_user, owner_user, "remove_access")
    _ensure_not_last_active_owner(target_user, owner_user, "remove_access")
    _ensure_secondary_user(target_user, owner_user, "remove_access")

    with transaction.atomic():
        target_user.is_active = False
        target_user.save(update_fields=["is_active"])
        release_active_session(target_user)
        record_audit_event(
            entreprise=target_user.entreprise,
            utilisateur=owner_user,
            action="utilisateur_acces_retire",
            module="users",
            objet_type="User",
            objet_id=target_user.id,
            description=f"Acces retire pour {target_user.email or target_user.username}.",
            metadata={"email": target_user.email or target_user.username},
        )
    return target_user
