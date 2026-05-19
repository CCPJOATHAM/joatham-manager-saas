from datetime import date, datetime, time

from django.db.models import Count, Q
from django.utils import timezone

from core.services.tenancy import get_object_for_entreprise, scope_queryset_to_entreprise

from ..models import InventoryLine, InventorySession


def _apply_date_filter(queryset, field_name, value, lookup_suffix):
    if not value:
        return queryset
    if isinstance(value, datetime):
        normalized = timezone.make_aware(value) if timezone.is_naive(value) else value
        return queryset.filter(**{f"{field_name}__{lookup_suffix}": normalized})
    if isinstance(value, date):
        normalized = datetime.combine(value, time.min if lookup_suffix == "gte" else time.max)
        normalized = timezone.make_aware(normalized)
        return queryset.filter(**{f"{field_name}__{lookup_suffix}": normalized})
    return queryset.filter(**{f"{field_name}__{lookup_suffix}": value})


def get_inventory_sessions_for_entreprise(entreprise, *, status=None, date_debut=None, date_fin=None):
    queryset = scope_queryset_to_entreprise(
        InventorySession.objects.select_related("created_by", "validated_by"),
        entreprise,
    )
    if status:
        queryset = queryset.filter(status=status)
    queryset = _apply_date_filter(queryset, "created_at", date_debut, "gte")
    queryset = _apply_date_filter(queryset, "created_at", date_fin, "lte")
    return queryset.order_by("-created_at", "-id")


def get_inventory_session_for_entreprise(entreprise, session_id):
    return get_object_for_entreprise(
        InventorySession.objects.select_related("created_by", "validated_by"),
        entreprise,
        id=session_id,
    )


def get_inventory_lines_for_session(entreprise, session):
    return (
        scope_queryset_to_entreprise(
            InventoryLine.objects.select_related("produit", "session"),
            entreprise,
        )
        .filter(session=session)
        .order_by("produit__nom", "id")
    )


def get_inventory_summary(entreprise, session):
    queryset = get_inventory_lines_for_session(entreprise, session)
    summary = queryset.aggregate(
        total_lines=Count("id"),
        counted_lines=Count("id", filter=Q(counted_quantity__isnull=False)),
        uncounted_lines=Count("id", filter=Q(counted_quantity__isnull=True)),
        positive_differences=Count("id", filter=Q(difference__gt=0)),
        negative_differences=Count("id", filter=Q(difference__lt=0)),
        balanced_lines=Count("id", filter=Q(counted_quantity__isnull=False, difference=0)),
    )
    return {
        "total_lines": summary["total_lines"] or 0,
        "counted_lines": summary["counted_lines"] or 0,
        "uncounted_lines": summary["uncounted_lines"] or 0,
        "positive_differences": summary["positive_differences"] or 0,
        "negative_differences": summary["negative_differences"] or 0,
        "balanced_lines": summary["balanced_lines"] or 0,
    }
