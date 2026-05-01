from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import F, Q
from django.utils import timezone

from joatham_users.models import EntrepriseInvitation
from joatham_users.services.invitations import REMINDER_ERROR, REMINDER_SENT, send_invitation_reminder


class Command(BaseCommand):
    help = "Envoie les relances securisees pour les invitations entreprise non utilisees."

    def handle(self, *args, **options):
        now = timezone.now()
        reminder_cutoff = now - timedelta(hours=24)
        invitations = (
            EntrepriseInvitation.objects.filter(
                is_used=False,
                expires_at__gt=now,
                created_at__lte=reminder_cutoff,
                reminder_count__lt=F("max_reminders"),
            )
            .filter(Q(last_reminder_sent_at__isnull=True) | Q(last_reminder_sent_at__lte=reminder_cutoff))
            .order_by("created_at", "id")
        )

        total = invitations.count()
        sent = 0
        skipped = 0
        errors = 0

        for invitation in invitations:
            result = send_invitation_reminder(invitation)
            if result.status == REMINDER_SENT:
                sent += 1
            elif result.status == REMINDER_ERROR:
                errors += 1
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Relances invitations terminees: total verifiees={total}, envoyees={sent}, ignorees={skipped}, erreurs={errors}"
            )
        )
