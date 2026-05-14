import logging
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone

from core.audit import record_audit_event
from core.services.quotas import PREMIUM_REQUIRED_MESSAGE, PlanQuotaExceeded, get_plan_quota_limit

from ..models import Entreprise, EntrepriseInvitation


logger = logging.getLogger(__name__)

User = get_user_model()

REMINDER_MIN_INTERVAL = timedelta(hours=24)
REMINDER_SENT = "sent"
REMINDER_SKIPPED = "skipped"
REMINDER_ERROR = "error"
COMPANY_INVITATION_SOURCE_PREFIX = "company_user_invite"
COMPANY_INVITATION_CANCELLED_PREFIX = "company_user_cancelled"
ALLOWED_INVITED_ROLES = {
    User.Role.GESTIONNAIRE,
    User.Role.COMPTABLE,
}


class InvitationEmailError(Exception):
    pass


@dataclass(frozen=True)
class InvitationReminderResult:
    status: str
    reason: str = ""

    @property
    def sent(self):
        return self.status == REMINDER_SENT


def _get_app_url():
    return getattr(settings, "JOATHAM_APP_URL", "https://app.joatham.com").rstrip("/")


def build_company_invitation_source(entreprise, role):
    return f"{COMPANY_INVITATION_SOURCE_PREFIX}:{entreprise.id}:{role}"


def build_cancelled_company_invitation_source(invitation):
    parsed = parse_company_invitation_source(invitation.source)
    if not parsed["is_company"]:
        return invitation.source
    return f"{COMPANY_INVITATION_CANCELLED_PREFIX}:{parsed['entreprise_id']}:{parsed['role']}"


def parse_company_invitation_source(source):
    parts = (source or "").split(":")
    if len(parts) != 3 or parts[0] not in {COMPANY_INVITATION_SOURCE_PREFIX, COMPANY_INVITATION_CANCELLED_PREFIX}:
        return {"is_company": False, "entreprise_id": None, "role": "", "cancelled": False}
    try:
        entreprise_id = int(parts[1])
    except (TypeError, ValueError):
        return {"is_company": False, "entreprise_id": None, "role": "", "cancelled": False}
    return {
        "is_company": True,
        "entreprise_id": entreprise_id,
        "role": parts[2],
        "cancelled": parts[0] == COMPANY_INVITATION_CANCELLED_PREFIX,
    }


def get_company_invitation_role(invitation):
    return parse_company_invitation_source(invitation.source)["role"]


def is_company_invitation_for(invitation, entreprise):
    parsed = parse_company_invitation_source(invitation.source)
    return parsed["is_company"] and parsed["entreprise_id"] == entreprise.id and not parsed["cancelled"]


def _split_full_name(full_name):
    full_name = (full_name or "").strip()
    if not full_name:
        return "", ""
    parts = full_name.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _ensure_invited_role(role):
    if role not in ALLOWED_INVITED_ROLES:
        raise ValueError("Vous pouvez inviter uniquement un gestionnaire ou un comptable.")


def _active_company_invitation_queryset(entreprise):
    return EntrepriseInvitation.objects.filter(
        source__startswith=f"{COMPANY_INVITATION_SOURCE_PREFIX}:{entreprise.id}:",
        is_used=False,
        expires_at__gt=timezone.now(),
    )


def _ensure_invitation_email_available(entreprise, email, *, exclude_invitation_id=None):
    normalized_email = (email or "").strip().lower()
    if User.objects.filter(entreprise=entreprise, email__iexact=normalized_email).exists():
        raise ValueError("Un utilisateur de cette entreprise utilise deja cet email.")
    if User.objects.filter(entreprise=entreprise, username__iexact=normalized_email).exists():
        raise ValueError("Un utilisateur de cette entreprise utilise deja cet email.")
    if User.objects.filter(email__iexact=normalized_email).exclude(entreprise=entreprise).exists():
        raise ValueError("Un compte existe deja avec cet email.")
    if User.objects.filter(username__iexact=normalized_email).exclude(entreprise=entreprise).exists():
        raise ValueError("Un compte existe deja avec cet email.")
    invitation_qs = _active_company_invitation_queryset(entreprise).filter(email__iexact=normalized_email)
    if exclude_invitation_id:
        invitation_qs = invitation_qs.exclude(id=exclude_invitation_id)
    if invitation_qs.exists():
        raise ValueError("Une invitation active existe deja pour cet email.")
    return normalized_email


def assert_company_invitation_quota_available(entreprise):
    limit = get_plan_quota_limit(entreprise, "max_utilisateurs", plan_field="max_utilisateurs")
    if limit is None:
        return

    Entreprise.objects.select_for_update().filter(pk=entreprise.pk).exists()
    user_count = User.objects.filter(entreprise=entreprise).count()
    pending_count = _active_company_invitation_queryset(entreprise).count()
    if user_count + pending_count >= limit:
        raise PlanQuotaExceeded(
            f"{PREMIUM_REQUIRED_MESSAGE} Votre plan permet jusqu'a {limit} utilisateur(s), invitations en attente incluses."
        )


def build_invitation_activation_url(invitation):
    parsed = parse_company_invitation_source(invitation.source)
    if parsed["is_company"] and not parsed["cancelled"]:
        return f"{_get_app_url()}{reverse('user_invitation_accept', args=[invitation.token])}"
    return f"{_get_app_url()}/signup/?invitation={quote(invitation.token)}"


def _get_invitation_email_context(invitation):
    return {
        "invitation": invitation,
        "activation_url": build_invitation_activation_url(invitation),
        "app_url": _get_app_url(),
        "support_email": "admin@joatham.com",
    }


def send_invitation_email(invitation):
    context = _get_invitation_email_context(invitation)
    try:
        text_body = render_to_string("joatham_users/emails/invitation.txt", context).strip()
        html_body = render_to_string("joatham_users/emails/invitation.html", context)
        email = EmailMultiAlternatives(
            "Votre acces JOATHAM Manager est pret",
            text_body,
            settings.DEFAULT_FROM_EMAIL,
            [invitation.email],
        )
        email.attach_alternative(html_body, "text/html")
        email.send(fail_silently=False)
    except Exception as exc:
        logger.exception(
            "Echec d'envoi d'invitation entreprise invitation_id=%s email=%s",
            invitation.id,
            invitation.email,
        )
        raise InvitationEmailError("L'invitation n'a pas pu etre envoyee par email.") from exc


@transaction.atomic
def create_company_invitation(*, entreprise, owner_user, full_name, email, role):
    _ensure_invited_role(role)
    assert_company_invitation_quota_available(entreprise)
    normalized_email = _ensure_invitation_email_available(entreprise, email)

    invitation = EntrepriseInvitation.objects.create(
        email=normalized_email,
        full_name=(full_name or "").strip(),
        source=build_company_invitation_source(entreprise, role),
    )
    send_invitation_email(invitation)
    record_audit_event(
        entreprise=entreprise,
        utilisateur=owner_user,
        action="utilisateur_invite",
        module="users",
        objet_type="EntrepriseInvitation",
        objet_id=invitation.id,
        description=f"Invitation envoyee a {normalized_email} pour le role {role}.",
        metadata={"email": normalized_email, "role": role},
    )
    return invitation


@transaction.atomic
def resend_company_invitation(*, invitation, entreprise, owner_user):
    if not is_company_invitation_for(invitation, entreprise) or invitation.is_used or invitation.is_expired:
        raise ValueError("Cette invitation n'est plus active.")

    send_invitation_email(invitation)
    invitation.last_reminder_sent_at = timezone.now()
    invitation.reminder_count += 1
    invitation.save(update_fields=["last_reminder_sent_at", "reminder_count"])
    record_audit_event(
        entreprise=entreprise,
        utilisateur=owner_user,
        action="invitation_renvoyee",
        module="users",
        objet_type="EntrepriseInvitation",
        objet_id=invitation.id,
        description=f"Invitation renvoyee a {invitation.email}.",
        metadata={"email": invitation.email, "role": get_company_invitation_role(invitation)},
    )
    return invitation


@transaction.atomic
def cancel_company_invitation(*, invitation, entreprise, owner_user):
    if not is_company_invitation_for(invitation, entreprise) or invitation.is_used:
        raise ValueError("Cette invitation ne peut pas etre annulee.")

    invitation.is_used = True
    invitation.source = build_cancelled_company_invitation_source(invitation)
    invitation.save(update_fields=["is_used", "source"])
    record_audit_event(
        entreprise=entreprise,
        utilisateur=owner_user,
        action="invitation_annulee",
        module="users",
        objet_type="EntrepriseInvitation",
        objet_id=invitation.id,
        description=f"Invitation annulee pour {invitation.email}.",
        metadata={"email": invitation.email, "role": get_company_invitation_role(invitation)},
    )
    return invitation


@transaction.atomic
def accept_company_invitation(*, invitation, password):
    parsed = parse_company_invitation_source(invitation.source)
    if not parsed["is_company"] or parsed["cancelled"] or invitation.is_used or invitation.is_expired:
        raise ValueError("Cette invitation n'est plus valide.")

    entreprise = Entreprise.objects.get(id=parsed["entreprise_id"])
    role = parsed["role"]
    _ensure_invited_role(role)
    normalized_email = _ensure_invitation_email_available(
        entreprise,
        invitation.email,
        exclude_invitation_id=invitation.id,
    )
    first_name, last_name = _split_full_name(invitation.full_name)

    user = User.objects.create_user(
        username=normalized_email,
        email=normalized_email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        role=role,
        entreprise=entreprise,
        is_active=True,
        email_verified=True,
        email_verified_at=timezone.now(),
    )
    invitation.is_used = True
    invitation.save(update_fields=["is_used"])
    record_audit_event(
        entreprise=entreprise,
        utilisateur=user,
        action="invitation_acceptee",
        module="users",
        objet_type="EntrepriseInvitation",
        objet_id=invitation.id,
        description=f"Invitation acceptee par {normalized_email}.",
        metadata={"email": normalized_email, "role": role},
    )
    return user


def _get_skip_reason(invitation, *, now):
    if invitation.is_used:
        return "used"
    if invitation.expires_at <= now:
        return "expired"
    if invitation.reminder_count >= invitation.max_reminders:
        return "max_reminders_reached"
    if invitation.created_at > now - REMINDER_MIN_INTERVAL:
        return "too_new"
    if invitation.last_reminder_sent_at and invitation.last_reminder_sent_at > now - REMINDER_MIN_INTERVAL:
        return "too_recent"
    return ""


def send_invitation_reminder(invitation):
    now = timezone.now()
    skip_reason = _get_skip_reason(invitation, now=now)
    if skip_reason:
        return InvitationReminderResult(status=REMINDER_SKIPPED, reason=skip_reason)

    context = _get_invitation_email_context(invitation)
    subject = "Votre acces JOATHAM Manager est pret"

    try:
        text_body = render_to_string("joatham_users/emails/invitation_reminder.txt", context).strip()
        html_body = render_to_string("joatham_users/emails/invitation_reminder.html", context)
        email = EmailMultiAlternatives(
            subject,
            text_body,
            settings.DEFAULT_FROM_EMAIL,
            [invitation.email],
        )
        email.attach_alternative(html_body, "text/html")
        email.send(fail_silently=False)
    except Exception:
        logger.exception(
            "Echec de relance d'invitation entreprise invitation_id=%s email=%s",
            invitation.id,
            invitation.email,
        )
        return InvitationReminderResult(status=REMINDER_ERROR, reason="email_error")

    invitation.last_reminder_sent_at = now
    invitation.reminder_count += 1
    invitation.save(update_fields=["last_reminder_sent_at", "reminder_count"])

    logger.info(
        "Relance d'invitation entreprise envoyee invitation_id=%s email=%s reminder_count=%s",
        invitation.id,
        invitation.email,
        invitation.reminder_count,
    )
    record_audit_event(
        entreprise=None,
        utilisateur=None,
        action="invitation_relance_envoyee",
        module="users",
        objet_type="EntrepriseInvitation",
        objet_id=invitation.id,
        description=f"Relance envoyee pour l'invitation {invitation.email}.",
        metadata={
            "email": invitation.email,
            "source": invitation.source,
            "reminder_count": invitation.reminder_count,
        },
    )
    return InvitationReminderResult(status=REMINDER_SENT, reason="")
