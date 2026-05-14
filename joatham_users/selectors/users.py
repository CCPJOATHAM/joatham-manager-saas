from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from joatham_users.models import EntrepriseInvitation
from joatham_users.services.invitations import (
    COMPANY_INVITATION_SOURCE_PREFIX,
    parse_company_invitation_source,
)


User = get_user_model()


def get_users_by_entreprise(entreprise, *, role=None, status=None, search=None):
    queryset = User.objects.filter(entreprise=entreprise)

    if role:
        queryset = queryset.filter(role=role)

    if status == "active":
        queryset = queryset.filter(is_active=True)
    elif status == "inactive":
        queryset = queryset.filter(is_active=False)

    if search:
        term = search.strip()
        queryset = queryset.filter(
            Q(email__icontains=term)
            | Q(username__icontains=term)
            | Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(telephone__icontains=term)
        )

    return queryset.order_by("role", "first_name", "last_name", "username")


def get_user_by_entreprise(entreprise, user_id):
    return get_users_by_entreprise(entreprise).get(id=user_id)


def get_active_company_invitations(entreprise):
    prefix = f"{COMPANY_INVITATION_SOURCE_PREFIX}:{entreprise.id}:"
    return EntrepriseInvitation.objects.filter(
        source__startswith=prefix,
        is_used=False,
        expires_at__gt=timezone.now(),
    ).order_by("-created_at", "-id")


def get_company_invitation_by_id(entreprise, invitation_id, *, active_only=True):
    queryset = EntrepriseInvitation.objects.filter(id=invitation_id)
    if active_only:
        queryset = queryset.filter(is_used=False, expires_at__gt=timezone.now())
    invitation = queryset.get()
    parsed = parse_company_invitation_source(invitation.source)
    if not parsed["is_company"] or parsed["entreprise_id"] != entreprise.id:
        raise EntrepriseInvitation.DoesNotExist
    return invitation


def get_company_user_metrics(entreprise, *, users=None, invitations=None):
    users = list(users if users is not None else get_users_by_entreprise(entreprise))
    invitations = list(invitations if invitations is not None else get_active_company_invitations(entreprise))
    return {
        "total_users": len(users),
        "active_users": sum(1 for user in users if user.is_active),
        "inactive_users": sum(1 for user in users if not user.is_active),
        "gestionnaire_count": sum(1 for user in users if user.normalized_role == User.Role.GESTIONNAIRE),
        "comptable_count": sum(1 for user in users if user.normalized_role == User.Role.COMPTABLE),
        "proprietaire_count": sum(1 for user in users if user.normalized_role == User.Role.PROPRIETAIRE),
        "pending_invitations": len(invitations),
    }
