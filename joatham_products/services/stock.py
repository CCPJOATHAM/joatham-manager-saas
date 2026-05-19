from decimal import Decimal, InvalidOperation

from django.db import transaction

from core.audit import record_audit_event

from ..models import Produit, StockMovement


class StockOperationError(ValueError):
    pass


POSITIVE_MOVEMENT_TYPES = {
    StockMovement.MovementType.MANUAL_ENTRY,
    StockMovement.MovementType.INVOICE_RESTORE,
    StockMovement.MovementType.ADJUSTMENT_POSITIVE,
    StockMovement.MovementType.TRANSFER_IN,
}

NEGATIVE_MOVEMENT_TYPES = {
    StockMovement.MovementType.MANUAL_EXIT,
    StockMovement.MovementType.INVOICE_SALE,
    StockMovement.MovementType.ADJUSTMENT_NEGATIVE,
    StockMovement.MovementType.TRANSFER_OUT,
}


def _normalize_positive_quantity(quantity):
    try:
        normalized = int(quantity)
    except (TypeError, ValueError) as exc:
        raise StockOperationError("La quantite doit etre un entier strictement positif.") from exc
    if normalized <= 0:
        raise StockOperationError("La quantite doit etre un entier strictement positif.")
    return normalized


def _normalize_source_id(source_id):
    if source_id in {None, ""}:
        return None
    try:
        return int(source_id)
    except (TypeError, ValueError) as exc:
        raise StockOperationError("La source du mouvement est invalide.") from exc


def _normalize_optional_non_negative_decimal(value, field_label):
    if value in {None, ""}:
        return None
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise StockOperationError(f"{field_label} est invalide.") from exc
    if normalized < 0:
        raise StockOperationError(f"{field_label} ne peut pas etre negatif.")
    return normalized


def _get_locked_product_for_entreprise(*, entreprise, produit):
    produit_id = getattr(produit, "id", produit)
    locked = (
        Produit.objects.select_for_update()
        .select_related("entreprise")
        .filter(id=produit_id, entreprise=entreprise)
        .first()
    )
    if locked is None:
        raise StockOperationError("Le produit selectionne est invalide pour cette entreprise.")
    return locked


def _build_movement_description(movement):
    return f"Mouvement de stock {movement.get_movement_type_display().lower()} pour {movement.produit.nom}."


def record_stock_movement(
    *,
    entreprise,
    produit,
    movement_type,
    quantity,
    stock_before,
    stock_after,
    unit_cost=None,
    reference="",
    reason="",
    comment="",
    source_app="",
    source_model="",
    source_id=None,
    created_by=None,
):
    if getattr(produit, "entreprise_id", None) != getattr(entreprise, "id", None):
        raise StockOperationError("Le produit selectionne est invalide pour cette entreprise.")

    quantity = _normalize_positive_quantity(quantity)
    unit_cost = _normalize_optional_non_negative_decimal(unit_cost, "Le cout unitaire")
    stock_before = int(stock_before or 0)
    stock_after = int(stock_after or 0)

    if stock_before < 0:
        raise StockOperationError("Le stock avant mouvement ne peut pas etre negatif.")
    if stock_after < 0:
        raise StockOperationError("Le stock apres mouvement ne peut pas etre negatif.")

    valid_types = {choice for choice, _label in StockMovement.MovementType.choices}
    if movement_type not in valid_types:
        raise StockOperationError("Le type de mouvement stock est invalide.")

    delta = stock_after - stock_before
    if movement_type in POSITIVE_MOVEMENT_TYPES and delta != quantity:
        raise StockOperationError("Le stock apres mouvement est incoherent avec ce type d'entree.")
    if movement_type in NEGATIVE_MOVEMENT_TYPES and delta != -quantity:
        raise StockOperationError("Le stock apres mouvement est incoherent avec ce type de sortie.")

    movement = StockMovement.objects.create(
        entreprise=entreprise,
        produit=produit,
        movement_type=movement_type,
        quantity=quantity,
        stock_before=stock_before,
        stock_after=stock_after,
        unit_cost=unit_cost,
        reference=(reference or "").strip(),
        reason=(reason or "").strip(),
        comment=(comment or "").strip(),
        source_app=(source_app or "").strip(),
        source_model=(source_model or "").strip(),
        source_id=_normalize_source_id(source_id),
        created_by=created_by,
    )

    record_audit_event(
        entreprise=entreprise,
        utilisateur=created_by,
        action="stock_movement_recorded",
        module="products",
        objet_type="StockMovement",
        objet_id=movement.id,
        description=_build_movement_description(movement),
        metadata={
            "produit_id": produit.id,
            "produit_nom": produit.nom,
            "movement_type": movement.movement_type,
            "quantity": movement.quantity,
            "stock_before": movement.stock_before,
            "stock_after": movement.stock_after,
            "unit_cost": str(movement.unit_cost) if movement.unit_cost is not None else "",
            "reference": movement.reference,
            "reason": movement.reason,
            "source_app": movement.source_app,
            "source_model": movement.source_model,
            "source_id": movement.source_id,
        },
    )
    return movement


def assert_stock_available(*, produit, quantity):
    quantity = _normalize_positive_quantity(quantity)
    stock_disponible = int(produit.quantite_stock or 0)
    if quantity > stock_disponible:
        raise StockOperationError(
            f"Stock insuffisant pour le produit {produit.nom}. "
            f"Stock disponible : {stock_disponible}, quantite demandee : {quantity}."
        )
    return stock_disponible


@transaction.atomic
def apply_manual_entry(
    *,
    entreprise,
    produit,
    quantity,
    utilisateur=None,
    unit_cost=None,
    reference="",
    reason="",
    comment="",
    source_app="",
    source_model="",
    source_id=None,
):
    locked_product = _get_locked_product_for_entreprise(entreprise=entreprise, produit=produit)
    quantity = _normalize_positive_quantity(quantity)
    stock_before = int(locked_product.quantite_stock or 0)
    stock_after = stock_before + quantity
    locked_product.quantite_stock = stock_after
    locked_product.save(update_fields=["quantite_stock"])
    return record_stock_movement(
        entreprise=entreprise,
        produit=locked_product,
        movement_type=StockMovement.MovementType.MANUAL_ENTRY,
        quantity=quantity,
        stock_before=stock_before,
        stock_after=stock_after,
        unit_cost=unit_cost,
        reference=reference,
        reason=reason,
        comment=comment,
        source_app=source_app,
        source_model=source_model,
        source_id=source_id,
        created_by=utilisateur,
    )


@transaction.atomic
def apply_manual_exit(
    *,
    entreprise,
    produit,
    quantity,
    utilisateur=None,
    reference="",
    reason="",
    comment="",
    source_app="",
    source_model="",
    source_id=None,
):
    locked_product = _get_locked_product_for_entreprise(entreprise=entreprise, produit=produit)
    quantity = _normalize_positive_quantity(quantity)
    stock_before = assert_stock_available(produit=locked_product, quantity=quantity)
    stock_after = stock_before - quantity
    locked_product.quantite_stock = stock_after
    locked_product.save(update_fields=["quantite_stock"])
    return record_stock_movement(
        entreprise=entreprise,
        produit=locked_product,
        movement_type=StockMovement.MovementType.MANUAL_EXIT,
        quantity=quantity,
        stock_before=stock_before,
        stock_after=stock_after,
        reference=reference,
        reason=reason,
        comment=comment,
        source_app=source_app,
        source_model=source_model,
        source_id=source_id,
        created_by=utilisateur,
    )


@transaction.atomic
def apply_adjustment(
    *,
    entreprise,
    produit,
    quantity,
    movement_type,
    utilisateur=None,
    unit_cost=None,
    reference="",
    reason="",
    comment="",
    source_app="",
    source_model="",
    source_id=None,
):
    if movement_type not in {
        StockMovement.MovementType.ADJUSTMENT_POSITIVE,
        StockMovement.MovementType.ADJUSTMENT_NEGATIVE,
    }:
        raise StockOperationError("Le type d'ajustement stock est invalide.")

    locked_product = _get_locked_product_for_entreprise(entreprise=entreprise, produit=produit)
    quantity = _normalize_positive_quantity(quantity)
    stock_before = int(locked_product.quantite_stock or 0)
    if movement_type == StockMovement.MovementType.ADJUSTMENT_POSITIVE:
        stock_after = stock_before + quantity
    else:
        assert_stock_available(produit=locked_product, quantity=quantity)
        stock_after = stock_before - quantity
    locked_product.quantite_stock = stock_after
    locked_product.save(update_fields=["quantite_stock"])
    return record_stock_movement(
        entreprise=entreprise,
        produit=locked_product,
        movement_type=movement_type,
        quantity=quantity,
        stock_before=stock_before,
        stock_after=stock_after,
        unit_cost=unit_cost,
        reference=reference,
        reason=reason,
        comment=comment,
        source_app=source_app,
        source_model=source_model,
        source_id=source_id,
        created_by=utilisateur,
    )


@transaction.atomic
def apply_invoice_sale(
    *,
    entreprise,
    produit,
    quantity,
    facture=None,
    utilisateur=None,
    unit_cost=None,
    reference="",
    reason="",
    comment="",
    source_app="",
    source_model="",
    source_id=None,
):
    locked_product = _get_locked_product_for_entreprise(entreprise=entreprise, produit=produit)
    quantity = _normalize_positive_quantity(quantity)
    stock_before = assert_stock_available(produit=locked_product, quantity=quantity)
    stock_after = stock_before - quantity
    locked_product.quantite_stock = stock_after
    locked_product.save(update_fields=["quantite_stock"])
    return record_stock_movement(
        entreprise=entreprise,
        produit=locked_product,
        movement_type=StockMovement.MovementType.INVOICE_SALE,
        quantity=quantity,
        stock_before=stock_before,
        stock_after=stock_after,
        unit_cost=unit_cost,
        reference=reference or getattr(facture, "numero", ""),
        reason=reason or "Sortie de stock liee a une facture.",
        comment=comment,
        source_app=source_app or ("joatham_billing" if facture is not None else ""),
        source_model=source_model or ("Facture" if facture is not None else ""),
        source_id=source_id if source_id is not None else getattr(facture, "id", None),
        created_by=utilisateur,
    )


@transaction.atomic
def restore_invoice_stock(
    *,
    entreprise,
    produit,
    quantity,
    facture=None,
    utilisateur=None,
    unit_cost=None,
    reference="",
    reason="",
    comment="",
    source_app="",
    source_model="",
    source_id=None,
):
    locked_product = _get_locked_product_for_entreprise(entreprise=entreprise, produit=produit)
    quantity = _normalize_positive_quantity(quantity)
    stock_before = int(locked_product.quantite_stock or 0)
    stock_after = stock_before + quantity
    locked_product.quantite_stock = stock_after
    locked_product.save(update_fields=["quantite_stock"])
    return record_stock_movement(
        entreprise=entreprise,
        produit=locked_product,
        movement_type=StockMovement.MovementType.INVOICE_RESTORE,
        quantity=quantity,
        stock_before=stock_before,
        stock_after=stock_after,
        unit_cost=unit_cost,
        reference=reference or getattr(facture, "numero", ""),
        reason=reason or "Restauration de stock liee a une facture annulee.",
        comment=comment,
        source_app=source_app or ("joatham_billing" if facture is not None else ""),
        source_model=source_model or ("Facture" if facture is not None else ""),
        source_id=source_id if source_id is not None else getattr(facture, "id", None),
        created_by=utilisateur,
    )


def recalculate_product_stock(*, entreprise, produit, opening_stock=0):
    locked_product = _get_locked_product_for_entreprise(entreprise=entreprise, produit=produit)
    stock = int(opening_stock or 0)
    for movement in StockMovement.objects.filter(entreprise=entreprise, produit=locked_product).order_by("created_at", "id"):
        if movement.movement_type in POSITIVE_MOVEMENT_TYPES:
            stock += movement.quantity
        elif movement.movement_type in NEGATIVE_MOVEMENT_TYPES:
            stock -= movement.quantity
        else:
            stock = movement.stock_after
    return stock
