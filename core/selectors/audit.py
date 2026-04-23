from datetime import datetime, time, timedelta, timezone as dt_timezone

from core.services.tenancy import scope_queryset_to_entreprise
from joatham_users.models import User

from ..models import ActivityLog


def get_activity_logs_by_entreprise(
    entreprise,
    *,
    module=None,
    utilisateur_id=None,
    action=None,
    role=None,
    date_from=None,
    date_to=None,
):
    queryset = scope_queryset_to_entreprise(
        ActivityLog.objects.select_related("utilisateur", "entreprise"),
        entreprise,
    )
    if module:
        queryset = queryset.filter(module=module)
    if utilisateur_id:
        queryset = queryset.filter(utilisateur_id=utilisateur_id)
    if action:
        queryset = queryset.filter(action=action)
    if role:
        queryset = queryset.filter(utilisateur__role=role)
    if date_from:
        date_from_start = datetime.combine(date_from, time.min, tzinfo=dt_timezone.utc)
        queryset = queryset.filter(date_creation__gte=date_from_start)
    if date_to:
        next_day_start = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=dt_timezone.utc)
        queryset = queryset.filter(date_creation__lt=next_day_start)
    return queryset.order_by("-date_creation", "-id")


def get_activity_modules_for_entreprise(entreprise):
    return list(
        scope_queryset_to_entreprise(ActivityLog.objects.all(), entreprise)
        .order_by("module")
        .values_list("module", flat=True)
        .distinct()
    )


def get_activity_actions_for_entreprise(entreprise):
    return list(
        scope_queryset_to_entreprise(ActivityLog.objects.all(), entreprise)
        .order_by("action")
        .values_list("action", flat=True)
        .distinct()
    )


def get_activity_users_for_entreprise(entreprise):
    return (
        User.objects.filter(activity_logs__entreprise=entreprise)
        .distinct()
        .order_by("username")
    )


def get_activity_roles_for_entreprise(entreprise):
    available_roles = (
        User.objects.filter(activity_logs__entreprise=entreprise)
        .exclude(role="")
        .order_by("role")
        .values_list("role", flat=True)
        .distinct()
    )
    labels = dict(User.Role.choices)
    return [{"value": role, "label": labels.get(role, role)} for role in available_roles]


def get_inscription_billing_history(inscription):
    actions = {
        "facture_inscription_creee",
        "facture_existante_liee_inscription",
        "facture_deliee_inscription",
    }
    entreprise = getattr(inscription, "entreprise", None)
    inscription_id = getattr(inscription, "id", None)
    if entreprise is None or inscription_id is None:
        return []

    candidate_logs = get_activity_logs_by_entreprise(
        entreprise,
        module="apprenants",
    ).filter(action__in=actions)

    history = []
    for log in candidate_logs:
        metadata = log.metadata or {}
        if log.objet_type == "InscriptionFormation" and log.objet_id == inscription_id:
            history.append(_build_inscription_billing_history_entry(log))
            continue

        metadata_inscription_id = metadata.get("inscription_id")
        if str(metadata_inscription_id) == str(inscription_id):
            history.append(_build_inscription_billing_history_entry(log))

    return history


def _build_inscription_billing_history_entry(log):
    metadata = log.metadata or {}
    return {
        "log": log,
        "date_creation": log.date_creation,
        "utilisateur": log.utilisateur,
        "action": log.action,
        "facture_numero": metadata.get("facture_numero", ""),
        "description": log.description,
    }
