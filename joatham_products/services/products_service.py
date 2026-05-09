from django.db import transaction

from core.audit import record_audit_event
from core.services.quotas import assert_product_quota_available

from ..models import Produit
from ..selectors.products import get_product_by_entreprise, get_products_by_entreprise
from .stock import apply_manual_entry


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
    initial_stock = int(quantite_stock or 0)
    produit = Produit.objects.create(
        entreprise=entreprise,
        nom=(nom or "").strip(),
        description=(description or "").strip(),
        reference=(reference or "").strip(),
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

    produit.nom = (nom or "").strip()
    produit.description = (description or "").strip()
    produit.reference = (reference or "").strip()
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
