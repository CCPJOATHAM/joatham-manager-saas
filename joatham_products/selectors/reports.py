from django.db.models import Count, F, Q, Sum

from .inventory import get_inventory_sessions_for_entreprise
from .products import get_products_by_entreprise
from .stock import get_recent_stock_movements, get_stock_movements_for_entreprise
from ..models import InventoryLine, InventorySession, StockMovement


ENTRY_MOVEMENT_TYPES = {
    StockMovement.MovementType.MANUAL_ENTRY,
    StockMovement.MovementType.INVOICE_RESTORE,
    StockMovement.MovementType.ADJUSTMENT_POSITIVE,
    StockMovement.MovementType.TRANSFER_IN,
}

EXIT_MOVEMENT_TYPES = {
    StockMovement.MovementType.MANUAL_EXIT,
    StockMovement.MovementType.INVOICE_SALE,
    StockMovement.MovementType.ADJUSTMENT_NEGATIVE,
    StockMovement.MovementType.TRANSFER_OUT,
}
def _get_filtered_movements(
    entreprise,
    *,
    produit=None,
    movement_type=None,
    date_debut=None,
    date_fin=None,
    source_app=None,
):
    return get_stock_movements_for_entreprise(
        entreprise,
        produit=produit,
        movement_type=movement_type,
        date_debut=date_debut,
        date_fin=date_fin,
        source_app=source_app,
    )


def get_stock_report_snapshot(
    entreprise,
    *,
    produit=None,
    movement_type=None,
    date_debut=None,
    date_fin=None,
    source_app=None,
):
    products = list(get_products_by_entreprise(entreprise))
    active_products = [product for product in products if product.actif]
    movements = _get_filtered_movements(
        entreprise,
        produit=produit,
        movement_type=movement_type,
        date_debut=date_debut,
        date_fin=date_fin,
        source_app=source_app,
    )
    inventory_sessions = get_inventory_sessions_for_entreprise(
        entreprise,
        date_debut=date_debut,
        date_fin=date_fin,
    )
    validated_inventory_ids = list(
        inventory_sessions.filter(status=InventorySession.Status.VALIDATED).values_list("id", flat=True)
    )
    inventory_lines = InventoryLine.objects.filter(
        entreprise=entreprise,
        session_id__in=validated_inventory_ids,
    )
    inventory_with_difference = (
        inventory_lines.filter(difference__isnull=False)
        .exclude(difference=0)
        .values("session_id")
        .distinct()
        .count()
    )

    movement_aggregates = movements.aggregate(
        total_mouvements=Count("id"),
        total_entrees=Sum("quantity", filter=Q(movement_type__in=ENTRY_MOVEMENT_TYPES)),
        total_sorties=Sum("quantity", filter=Q(movement_type__in=EXIT_MOVEMENT_TYPES)),
        total_adjustments_positive=Sum(
            "quantity",
            filter=Q(movement_type=StockMovement.MovementType.ADJUSTMENT_POSITIVE),
        ),
        total_adjustments_negative=Sum(
            "quantity",
            filter=Q(movement_type=StockMovement.MovementType.ADJUSTMENT_NEGATIVE),
        ),
    )
    low_stock_count = (
        get_products_by_entreprise(entreprise)
        .filter(actif=True, quantite_stock__lte=F("seuil_alerte"))
        .count()
    )

    return {
        "total_produits_actifs": len(active_products),
        "produits_en_stock": sum(1 for product in active_products if product.stock_status == "en_stock"),
        "produits_rupture": sum(1 for product in active_products if product.stock_status == "rupture"),
        "produits_stock_faible": low_stock_count,
        "total_mouvements": movement_aggregates["total_mouvements"] or 0,
        "total_entrees": movement_aggregates["total_entrees"] or 0,
        "total_sorties": movement_aggregates["total_sorties"] or 0,
        "total_ajustements_positifs": movement_aggregates["total_adjustments_positive"] or 0,
        "total_ajustements_negatifs": movement_aggregates["total_adjustments_negative"] or 0,
        "inventaires_valides": len(validated_inventory_ids),
        "inventaires_avec_ecarts": inventory_with_difference,
    }


def get_stock_report_product_summary(
    entreprise,
    *,
    produit=None,
    movement_type=None,
    date_debut=None,
    date_fin=None,
    source_app=None,
):
    selected_product_id = getattr(produit, "id", produit) if produit is not None else None
    products = list(get_products_by_entreprise(entreprise))
    if selected_product_id:
        products = [product for product in products if product.id == selected_product_id]

    movements = list(
        _get_filtered_movements(
            entreprise,
            produit=produit,
            movement_type=movement_type,
            date_debut=date_debut,
            date_fin=date_fin,
            source_app=source_app,
        )
    )
    movement_map = {}
    for movement in movements:
        bucket = movement_map.setdefault(
            movement.produit_id,
            {"entries": 0, "exits": 0, "last_movement_at": None},
        )
        if movement.movement_type in ENTRY_MOVEMENT_TYPES:
            bucket["entries"] += movement.quantity
        if movement.movement_type in EXIT_MOVEMENT_TYPES:
            bucket["exits"] += movement.quantity
        if bucket["last_movement_at"] is None or movement.created_at > bucket["last_movement_at"]:
            bucket["last_movement_at"] = movement.created_at

    rows = []
    for product in products:
        stats = movement_map.get(product.id, {"entries": 0, "exits": 0, "last_movement_at": None})
        status = product.stock_status
        rows.append(
            {
                "product": product,
                "stock_actuel": product.quantite_stock,
                "seuil_alerte": product.seuil_alerte,
                "statut_stock": status,
                "statut_stock_label": {
                    "en_stock": "En stock",
                    "stock_faible": "Stock faible",
                    "rupture": "Rupture",
                }[status],
                "total_entrees": stats["entries"],
                "total_sorties": stats["exits"],
                "solde_mouvements": stats["entries"] - stats["exits"],
                "dernier_mouvement": stats["last_movement_at"],
            }
        )
    return rows


def get_stock_report_movement_type_summary(
    entreprise,
    *,
    produit=None,
    movement_type=None,
    date_debut=None,
    date_fin=None,
    source_app=None,
):
    movements = _get_filtered_movements(
        entreprise,
        produit=produit,
        movement_type=movement_type,
        date_debut=date_debut,
        date_fin=date_fin,
        source_app=source_app,
    )
    summary = (
        movements.values("movement_type")
        .annotate(
            movement_count=Count("id"),
            total_quantity=Sum("quantity"),
        )
        .order_by("movement_type")
    )
    label_map = dict(StockMovement.MovementType.choices)
    return [
        {
            "movement_type": row["movement_type"],
            "movement_label": label_map.get(row["movement_type"], row["movement_type"]),
            "movement_count": row["movement_count"],
            "total_quantity": row["total_quantity"] or 0,
        }
        for row in summary
    ]


def get_stock_report_inventory_summary(entreprise, *, status=None, date_debut=None, date_fin=None):
    sessions = get_inventory_sessions_for_entreprise(
        entreprise,
        status=status,
        date_debut=date_debut,
        date_fin=date_fin,
    )
    status_counts = sessions.aggregate(
        draft_count=Count("id", filter=Q(status=InventorySession.Status.DRAFT)),
        in_progress_count=Count("id", filter=Q(status=InventorySession.Status.IN_PROGRESS)),
        closed_count=Count("id", filter=Q(status=InventorySession.Status.CLOSED)),
        validated_count=Count("id", filter=Q(status=InventorySession.Status.VALIDATED)),
        cancelled_count=Count("id", filter=Q(status=InventorySession.Status.CANCELLED)),
    )
    validated_ids = list(sessions.filter(status=InventorySession.Status.VALIDATED).values_list("id", flat=True))
    lines = InventoryLine.objects.filter(entreprise=entreprise, session_id__in=validated_ids)
    line_summary = lines.aggregate(
        positive_differences=Count("id", filter=Q(difference__gt=0)),
        negative_differences=Count("id", filter=Q(difference__lt=0)),
    )
    with_diff = (
        lines.exclude(difference=0)
        .values("session_id")
        .distinct()
        .count()
    )
    return {
        "draft_count": status_counts["draft_count"] or 0,
        "in_progress_count": status_counts["in_progress_count"] or 0,
        "closed_count": status_counts["closed_count"] or 0,
        "validated_count": status_counts["validated_count"] or 0,
        "cancelled_count": status_counts["cancelled_count"] or 0,
        "inventories_with_differences": with_diff,
        "positive_differences": line_summary["positive_differences"] or 0,
        "negative_differences": line_summary["negative_differences"] or 0,
        "recent_inventories": list(sessions[:5]),
    }


def get_recent_stock_activity(
    entreprise,
    *,
    limit=20,
    produit=None,
    movement_type=None,
    date_debut=None,
    date_fin=None,
    source_app=None,
):
    return get_recent_stock_movements(
        entreprise,
        limit=limit,
        produit=produit,
        movement_type=movement_type,
        date_debut=date_debut,
        date_fin=date_fin,
        source_app=source_app,
    )
