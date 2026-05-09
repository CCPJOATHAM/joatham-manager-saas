from django.db import transaction
from django.utils import timezone

from core.audit import record_audit_event

from ..models import InventoryLine, InventorySession, Produit, StockMovement
from .stock import StockOperationError, apply_adjustment


class InventoryOperationError(ValueError):
    pass


def _get_locked_session_for_entreprise(*, entreprise, session):
    session_id = getattr(session, "id", session)
    locked = (
        InventorySession.objects.select_for_update()
        .select_related("entreprise", "created_by", "validated_by")
        .filter(id=session_id, entreprise=entreprise)
        .first()
    )
    if locked is None:
        raise InventoryOperationError("La session d'inventaire est invalide pour cette entreprise.")
    return locked


def _get_locked_line_for_entreprise(*, entreprise, session, line):
    line_id = getattr(line, "id", line)
    locked = (
        InventoryLine.objects.select_for_update()
        .select_related("session", "produit")
        .filter(id=line_id, entreprise=entreprise, session=session)
        .first()
    )
    if locked is None:
        raise InventoryOperationError("La ligne d'inventaire est invalide pour cette entreprise.")
    return locked


def _ensure_session_mutable(session):
    if session.status == InventorySession.Status.VALIDATED:
        raise InventoryOperationError("Une session validee ne peut plus etre modifiee.")
    if session.status == InventorySession.Status.CANCELLED:
        raise InventoryOperationError("Une session annulee ne peut plus etre modifiee.")


def _normalize_non_negative_quantity(quantity):
    if quantity in {None, ""}:
        return None
    try:
        normalized = int(quantity)
    except (TypeError, ValueError) as exc:
        raise InventoryOperationError("La quantite comptee doit etre un entier positif ou nul.") from exc
    if normalized < 0:
        raise InventoryOperationError("La quantite comptee doit etre un entier positif ou nul.")
    return normalized


@transaction.atomic
def create_inventory_session(*, entreprise, name, comment="", created_by=None, utilisateur=None, include_active_products=True):
    created_by = created_by or utilisateur
    session = InventorySession.objects.create(
        entreprise=entreprise,
        name=(name or "").strip(),
        comment=(comment or "").strip(),
        status=InventorySession.Status.DRAFT,
        created_by=created_by,
    )

    if include_active_products:
        add_products_to_inventory(entreprise=entreprise, session=session)

    record_audit_event(
        entreprise=entreprise,
        utilisateur=created_by,
        action="inventory_session_created",
        module="products",
        objet_type="InventorySession",
        objet_id=session.id,
        description=f"Session d'inventaire creee : {session.name}.",
        metadata={
            "status": session.status,
            "include_active_products": include_active_products,
        },
    )
    return session


@transaction.atomic
def start_inventory_session(*, entreprise, session=None, session_id=None):
    session = session if session is not None else session_id
    session = _get_locked_session_for_entreprise(entreprise=entreprise, session=session)
    _ensure_session_mutable(session)
    if session.status not in {InventorySession.Status.DRAFT, InventorySession.Status.IN_PROGRESS}:
        raise InventoryOperationError("Seule une session brouillon peut etre demarree.")
    if session.status == InventorySession.Status.IN_PROGRESS:
        return session
    session.status = InventorySession.Status.IN_PROGRESS
    session.started_at = session.started_at or timezone.now()
    session.save(update_fields=["status", "started_at", "updated_at"])
    return session


@transaction.atomic
def add_products_to_inventory(*, entreprise, session=None, session_id=None, produits=None):
    session = session if session is not None else session_id
    session = _get_locked_session_for_entreprise(entreprise=entreprise, session=session)
    _ensure_session_mutable(session)
    if session.status not in {InventorySession.Status.DRAFT, InventorySession.Status.IN_PROGRESS}:
        raise InventoryOperationError("Impossible d'ajouter des produits a cette session d'inventaire.")

    if produits is None:
        produits_queryset = Produit.objects.filter(entreprise=entreprise, actif=True).order_by("nom", "id")
    else:
        product_ids = [getattr(produit, "id", produit) for produit in produits]
        produits_queryset = Produit.objects.filter(entreprise=entreprise, id__in=product_ids).order_by("nom", "id")

    existing_ids = set(InventoryLine.objects.filter(session=session).values_list("produit_id", flat=True))
    lines_to_create = []
    for produit in produits_queryset:
        if produit.id in existing_ids:
            continue
        lines_to_create.append(
            InventoryLine(
                session=session,
                entreprise=entreprise,
                produit=produit,
                theoretical_quantity=int(produit.quantite_stock or 0),
                counted_quantity=None,
                difference=0,
            )
        )
    if lines_to_create:
        InventoryLine.objects.bulk_create(lines_to_create)
    return session


@transaction.atomic
def record_inventory_count(*, entreprise, session=None, session_id=None, line=None, line_id=None, counted_quantity=None, comment=""):
    session = session if session is not None else session_id
    line = line if line is not None else line_id
    session = _get_locked_session_for_entreprise(entreprise=entreprise, session=session)
    _ensure_session_mutable(session)
    if session.status != InventorySession.Status.IN_PROGRESS:
        raise InventoryOperationError("Le comptage n'est autorise que pour une session en cours.")

    line = _get_locked_line_for_entreprise(entreprise=entreprise, session=session, line=line)
    line.counted_quantity = _normalize_non_negative_quantity(counted_quantity)
    line.comment = (comment or "").strip()
    line.save()
    return line


@transaction.atomic
def close_inventory_session(*, entreprise, session=None, session_id=None):
    session = session if session is not None else session_id
    session = _get_locked_session_for_entreprise(entreprise=entreprise, session=session)
    _ensure_session_mutable(session)
    if session.status != InventorySession.Status.IN_PROGRESS:
        raise InventoryOperationError("Seule une session en cours peut etre cloturee.")
    if not session.lines.exists():
        raise InventoryOperationError("Impossible de cloturer un inventaire sans ligne.")
    session.status = InventorySession.Status.CLOSED
    session.closed_at = timezone.now()
    session.save(update_fields=["status", "closed_at", "updated_at"])
    return session


@transaction.atomic
def validate_inventory_session(*, entreprise, session=None, session_id=None, validated_by=None, utilisateur=None):
    session = session if session is not None else session_id
    validated_by = validated_by or utilisateur
    session = _get_locked_session_for_entreprise(entreprise=entreprise, session=session)
    _ensure_session_mutable(session)
    if session.status != InventorySession.Status.CLOSED:
        raise InventoryOperationError("Seule une session cloturee peut etre validee.")

    lines = list(
        InventoryLine.objects.select_for_update()
        .select_related("produit")
        .filter(session=session, entreprise=entreprise)
    )
    if not lines:
        raise InventoryOperationError("Impossible de valider un inventaire sans ligne.")
    if any(line.counted_quantity is None for line in lines):
        raise InventoryOperationError("Toutes les lignes doivent etre comptees avant validation.")

    reference = f"INV-{session.id}"
    for line in lines:
        if line.difference > 0:
            apply_adjustment(
                entreprise=entreprise,
                produit=line.produit,
                quantity=line.difference,
                movement_type=StockMovement.MovementType.ADJUSTMENT_POSITIVE,
                utilisateur=validated_by,
                reference=reference,
                reason="Ajustement inventaire physique",
                comment=line.comment,
                source_app="joatham_products",
                source_model="InventoryLine",
                source_id=line.id,
            )
        elif line.difference < 0:
            apply_adjustment(
                entreprise=entreprise,
                produit=line.produit,
                quantity=abs(line.difference),
                movement_type=StockMovement.MovementType.ADJUSTMENT_NEGATIVE,
                utilisateur=validated_by,
                reference=reference,
                reason="Ajustement inventaire physique",
                comment=line.comment,
                source_app="joatham_products",
                source_model="InventoryLine",
                source_id=line.id,
            )

    session.status = InventorySession.Status.VALIDATED
    session.validated_at = timezone.now()
    session.validated_by = validated_by
    session.save(update_fields=["status", "validated_at", "validated_by", "updated_at"])

    record_audit_event(
        entreprise=entreprise,
        utilisateur=validated_by,
        action="inventory_session_validated",
        module="products",
        objet_type="InventorySession",
        objet_id=session.id,
        description=f"Session d'inventaire validee : {session.name}.",
        metadata={"reference": reference},
    )
    return session


@transaction.atomic
def cancel_inventory_session(*, entreprise, session=None, session_id=None):
    session = session if session is not None else session_id
    session = _get_locked_session_for_entreprise(entreprise=entreprise, session=session)
    if session.status == InventorySession.Status.VALIDATED:
        raise InventoryOperationError("Une session validee ne peut pas etre annulee.")
    if session.status == InventorySession.Status.CANCELLED:
        raise InventoryOperationError("Cette session d'inventaire est deja annulee.")
    session.status = InventorySession.Status.CANCELLED
    session.save(update_fields=["status", "updated_at"])
    return session
