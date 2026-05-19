from decimal import Decimal, InvalidOperation

from django.db import transaction

from core.audit import record_audit_event
from core.services.quotas import assert_product_quota_available

from ..models import Produit
from ..selectors.products import get_product_by_entreprise, get_products_by_entreprise
from .stock import apply_manual_entry


class ProductOperationError(ValueError):
    pass


def _normalize_required_text(value, message):
    normalized = (value or "").strip()
    if not normalized:
        raise ProductOperationError(message)
    return normalized


def _normalize_optional_text(value):
    return (value or "").strip()


def _normalize_non_negative_decimal(value, field_label):
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ProductOperationError(f"{field_label} est invalide.") from exc
    if normalized < 0:
        raise ProductOperationError(f"{field_label} ne peut pas etre negatif.")
    return normalized


def _normalize_non_negative_integer(value, field_label):
    if value in {None, ""}:
        return 0
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ProductOperationError(f"{field_label} est invalide.") from exc
    if normalized < 0:
        raise ProductOperationError(f"{field_label} ne peut pas etre negatif.")
    return normalized


def _ensure_reference_available(entreprise, reference, *, product_id=None):
    if not reference:
        return
    queryset = Produit.objects.filter(entreprise=entreprise, reference=reference)
    if product_id is not None:
        queryset = queryset.exclude(id=product_id)
    if queryset.exists():
        raise ProductOperationError("Une autre fiche produit utilise deja cette reference.")


def list_products_for_entreprise(entreprise, *, stock_filter=None):
    return get_products_by_entreprise(entreprise, stock_filter=stock_filter)


@transaction.atomic
def create_product_for_entreprise(
    *,
    entreprise,
    nom,
    description="",
    reference="",
    prix_unitaire,
    quantite_stock,
    seuil_alerte,
    actif,
    utilisateur=None,
):
    assert_product_quota_available(entreprise)
    nom = _normalize_required_text(nom, "Le nom du produit est obligatoire.")
    description = _normalize_optional_text(description)
    reference = _normalize_optional_text(reference)
    prix_unitaire = _normalize_non_negative_decimal(prix_unitaire, "Le prix unitaire")
    initial_stock = _normalize_non_negative_integer(quantite_stock, "Le stock initial")
    seuil_alerte = _normalize_non_negative_integer(seuil_alerte, "Le seuil d'alerte")
    _ensure_reference_available(entreprise, reference)
    produit = Produit.objects.create(
        entreprise=entreprise,
        nom=nom,
        description=description,
        reference=reference,
        prix_unitaire=prix_unitaire,
        quantite_stock=0,
        seuil_alerte=seuil_alerte,
        actif=actif,
    )
    if initial_stock > 0:
        apply_manual_entry(
            entreprise=entreprise,
            produit=produit,
            quantity=initial_stock,
            utilisateur=utilisateur,
            reference=f"INIT-{produit.id}",
            reason="Stock initial produit",
            comment="Stock initial enregistre a la creation du produit.",
        )
        produit.refresh_from_db(fields=["quantite_stock"])
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="produit_cree",
        module="products",
        objet_type="Produit",
        objet_id=produit.id,
        description=f"Produit cree : {produit.nom}.",
        metadata={
            "reference": produit.reference,
            "description": produit.description,
            "prix_unitaire": str(produit.prix_unitaire),
            "quantite_stock": produit.quantite_stock,
            "seuil_alerte": produit.seuil_alerte,
        },
    )
    return produit


def update_product_for_entreprise(
    *,
    entreprise,
    product_id,
    nom,
    description="",
    reference,
    prix_unitaire,
    quantite_stock,
    seuil_alerte,
    actif,
    utilisateur=None,
):
    produit = get_product_by_entreprise(entreprise, product_id)
    nom = _normalize_required_text(nom, "Le nom du produit est obligatoire.")
    description = _normalize_optional_text(description)
    reference = _normalize_optional_text(reference)
    prix_unitaire = _normalize_non_negative_decimal(prix_unitaire, "Le prix unitaire")
    seuil_alerte = _normalize_non_negative_integer(seuil_alerte, "Le seuil d'alerte")
    _ensure_reference_available(entreprise, reference, product_id=produit.id)

    produit.nom = nom
    produit.description = description
    produit.reference = reference
    produit.prix_unitaire = prix_unitaire
    produit.seuil_alerte = seuil_alerte
    produit.actif = actif
    produit.save()

    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="produit_modifie",
        module="products",
        objet_type="Produit",
        objet_id=produit.id,
        description=f"Produit modifie : {produit.nom}.",
        metadata={
            "reference": produit.reference,
            "description": produit.description,
            "prix_unitaire": str(produit.prix_unitaire),
            "quantite_stock": produit.quantite_stock,
            "seuil_alerte": produit.seuil_alerte,
            "actif": produit.actif,
        },
    )

    return produit
