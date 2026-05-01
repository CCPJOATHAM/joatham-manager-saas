import logging
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from core.audit import record_audit_event

from ..models import EntrepriseInvitation


logger = logging.getLogger(__name__)

REMINDER_MIN_INTERVAL = timedelta(hours=24)
REMINDER_SENT = "sent"
REMINDER_SKIPPED = "skipped"
REMINDER_ERROR = "error"


@dataclass(frozen=True)
class InvitationReminderResult:
    status: str
    reason: str = ""

    @property
    def sent(self):
        return self.status == REMINDER_SENT


def _get_app_url():
    return getattr(settings, "JOATHAM_APP_URL", "https://app.joatham.com").rstrip("/")


def build_invitation_activation_url(invitation):
    return f"{_get_app_url()}/signup/?invitation={quote(invitation.token)}"


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

    context = {
        "invitation": invitation,
        "activation_url": build_invitation_activation_url(invitation),
        "app_url": _get_app_url(),
        "support_email": "admin@joatham.com",
    }
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
