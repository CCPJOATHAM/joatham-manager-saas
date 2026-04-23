import logging

from .models import ActivityLog


logger = logging.getLogger(__name__)


def record_audit_event(
    *,
    entreprise,
    utilisateur=None,
    action,
    module,
    objet_type="",
    objet_id=None,
    description,
    metadata=None,
    fail_silently=True,
):
    try:
        return ActivityLog.objects.create(
            entreprise=entreprise,
            utilisateur=utilisateur,
            action=action,
            module=module,
            objet_type=objet_type,
            objet_id=objet_id,
            description=description,
            metadata=metadata or {},
        )
    except Exception:
        logger.exception(
            "Erreur lors de l'enregistrement d'un evenement d'audit",
            extra={
                "entreprise_id": getattr(entreprise, "id", None),
                "utilisateur_id": getattr(utilisateur, "id", None),
                "action": action,
                "module": module,
            },
        )
        if not fail_silently:
            raise
        return None
