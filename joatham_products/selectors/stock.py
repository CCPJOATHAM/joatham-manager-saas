from datetime import date, datetime, time

from core.services.tenancy import scope_queryset_to_entreprise

from ..models import StockMovement


def _apply_date_filter(queryset, field_name, value, lookup_suffix):
    if not value:
        return queryset
    if isinstance(value, datetime):
        return queryset.filter(**{f"{field_name}__{lookup_suffix}": value})
    if isinstance(value, date):
        normalized = datetime.combine(value, time.min if lookup_suffix == "gte" else time.max)
        return queryset.filter(**{f"{field_name}__{lookup_suffix}": normalized})
    return queryset.filter(**{f"{field_name}__{lookup_suffix}": value})


def get_stock_movements_for_entreprise(
    entreprise,
    *,
    produit=None,
    movement_type=None,
    date_debut=None,
    date_fin=None,
    source_app=None,
    source_model=None,
    source_id=None,
):
    queryset = scope_queryset_to_entreprise(
        StockMovement.objects.select_related("produit", "created_by"),
        entreprise,
    )

    if produit is not None:
        produit_id = getattr(produit, "id", produit)
        queryset = queryset.filter(produit_id=produit_id)
    if movement_type:
        queryset = queryset.filter(movement_type=movement_type)
    if source_app:
        queryset = queryset.filter(source_app=source_app)
    if source_model:
        queryset = queryset.filter(source_model=source_model)
    if source_id not in {None, ""}:
        queryset = queryset.filter(source_id=source_id)

    queryset = _apply_date_filter(queryset, "created_at", date_debut, "gte")
    queryset = _apply_date_filter(queryset, "created_at", date_fin, "lte")
    return queryset.order_by("-created_at", "-id")


def get_stock_movements_for_product(
    entreprise,
    produit,
    *,
    movement_type=None,
    date_debut=None,
    date_fin=None,
    source_app=None,
    source_model=None,
    source_id=None,
):
    return get_stock_movements_for_entreprise(
        entreprise,
        produit=produit,
        movement_type=movement_type,
        date_debut=date_debut,
        date_fin=date_fin,
        source_app=source_app,
        source_model=source_model,
        source_id=source_id,
    )


def get_recent_stock_movements(
    entreprise,
    *,
    limit=10,
    produit=None,
    movement_type=None,
    date_debut=None,
    date_fin=None,
    source_app=None,
    source_model=None,
    source_id=None,
):
    queryset = get_stock_movements_for_entreprise(
        entreprise,
        produit=produit,
        movement_type=movement_type,
        date_debut=date_debut,
        date_fin=date_fin,
        source_app=source_app,
        source_model=source_model,
        source_id=source_id,
    )
    return queryset[:limit]
