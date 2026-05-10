import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.db.models import Model, QuerySet
from django.utils.functional import Promise

from .models import ActivityLog


logger = logging.getLogger(__name__)


def _make_json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Promise):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Model):
        return getattr(value, "pk", None) if getattr(value, "pk", None) is not None else str(value)
    if isinstance(value, QuerySet):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(item) for item in value]
    return str(value)


def _safe_metadata(metadata):
    return _make_json_safe(metadata or {})


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
            action=str(action),
            module=str(module),
            objet_type=str(objet_type),
            objet_id=objet_id,
            description=str(description),
            metadata=_safe_metadata(metadata),
        )
    except Exception:
        logger.exception(
            "Erreur lors de l'enregistrement d'un evenement d'audit",
            extra={
                "entreprise_id": getattr(entreprise, "id", None),
                "utilisateur_id": getattr(utilisateur, "id", None),
                "audit_action": action,
                "audit_module": module,
            },
        )
        if not fail_silently:
            raise
        return None
