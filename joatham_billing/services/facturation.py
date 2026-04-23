import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404

from core.audit import record_audit_event
from joatham_clients.models import Client
from joatham_comptabilite.services.comptabilisation import (
    comptabiliser_facture_emise,
    comptabiliser_paiement_facture,
)
from joatham_products.models import Produit
from joatham_users.permissions import user_has_permission

from ..exceptions import PaiementFacturationError, PermissionFacturationError, WorkflowFacturationError
from ..models import Facture, FactureHistorique, LigneFacture, PaiementFacture, Service
from ..selectors.billing import get_facture_by_entreprise, get_facture_queryset, get_factures_by_entreprise, get_services_by_entreprise

logger = logging.getLogger(__name__)


def _prepare_ligne_facture(*, entreprise, ligne):
    designation = (ligne.get("designation") or "").strip()
    service_id = (ligne.get("service_id") or "").strip()
    product_id = (ligne.get("product_id") or "").strip()
    raw_prix = ligne.get("prix")
    prix_source = raw_prix
    produit = None
    service = None

    if product_id:
        produit = Produit.objects.filter(id=product_id, entreprise=entreprise).first()
        if produit is None:
            raise WorkflowFacturationError("Le produit selectionne est invalide pour cette entreprise.")
        if not designation:
            designation = (produit.description or "").strip() or produit.nom
        if raw_prix in {None, ""}:
            prix_source = produit.prix_unitaire

    if service_id and produit is None:
        service = Service.objects.filter(id=service_id, entreprise=entreprise).first()
        if service is None:
            raise WorkflowFacturationError("Le service selectionne est invalide pour cette entreprise.")
        if not designation:
            designation = service.nom
        if raw_prix in {None, ""}:
            prix_source = service.prix

    if not designation:
        return "", 0, Decimal("0"), None, None

    quantite = int(ligne.get("quantite") or 0)
    prix_unitaire = Decimal(prix_source or 0)
    return designation, quantite, prix_unitaire, produit, service


def _build_lignes_payload(*, entreprise, lignes):
    prepared_lignes = []

    for ligne in lignes or []:
        designation, quantite, prix_unitaire, produit, service = _prepare_ligne_facture(
            entreprise=entreprise,
            ligne=ligne,
        )
        if not designation:
            continue

        if quantite <= 0:
            raise WorkflowFacturationError("Chaque ligne de facture doit avoir une quantite strictement positive.")
        if prix_unitaire < 0:
            raise WorkflowFacturationError("Le prix unitaire ne peut pas etre negatif.")

        prepared_lignes.append(
            {
                "designation": designation,
                "quantite": quantite,
                "prix_unitaire": prix_unitaire,
                "produit": produit,
                "service": service,
            }
        )

    if not prepared_lignes:
        raise WorkflowFacturationError("Une facture doit contenir au moins une ligne.")

    return prepared_lignes


def _get_requested_product_quantities(lignes):
    requested = {}

    for ligne in lignes:
        produit = ligne.get("produit")
        if produit is None:
            continue
        requested[produit.id] = requested.get(produit.id, 0) + int(ligne["quantite"])

    return requested


def _ensure_stock_available(*, entreprise, lignes):
    requested = _get_requested_product_quantities(lignes)
    if not requested:
        return {}

    products = {
        produit.id: produit
        for produit in Produit.objects.select_for_update().filter(
            entreprise=entreprise,
            id__in=requested.keys(),
        )
    }

    for produit_id, quantite_demandee in requested.items():
        produit = products.get(produit_id)
        if produit is None:
            raise WorkflowFacturationError("Le produit selectionne est invalide pour cette entreprise.")

        stock_disponible = int(produit.quantite_stock or 0)
        if quantite_demandee > stock_disponible:
            raise WorkflowFacturationError(
                f"Stock insuffisant pour le produit {produit.nom}. "
                f"Stock disponible : {stock_disponible}, quantite demandee : {quantite_demandee}."
            )

    return products


def _get_facture_product_quantities(facture):
    requested = {}

    for ligne in facture.lignes.select_related("produit").all():
        if ligne.produit_id is None:
            continue
        requested[ligne.produit_id] = requested.get(ligne.produit_id, 0) + int(ligne.quantite)

    return requested


def _mark_facture_stock_state(*, facture, applied):
    if facture.stock_applique == applied:
        return
    facture.stock_applique = applied
    facture.save(update_fields=["stock_applique"])


def _audit_stock_movement(*, facture, produit, quantite, stock_avant, stock_apres, user, action, description):
    record_audit_event(
        entreprise=facture.entreprise,
        utilisateur=user,
        action=action,
        module="products",
        objet_type="Produit",
        objet_id=produit.id,
        description=description,
        metadata={
            "facture_id": facture.id,
            "facture_numero": facture.numero,
            "produit_id": produit.id,
            "produit_nom": produit.nom,
            "quantite": quantite,
            "stock_avant": stock_avant,
            "stock_apres": stock_apres,
        },
    )


def apply_stock_for_facture(*, facture, user):
    if facture.stock_applique:
        return

    requested = _get_facture_product_quantities(facture)
    if not requested:
        _mark_facture_stock_state(facture=facture, applied=True)
        return

    products = {
        produit.id: produit
        for produit in Produit.objects.select_for_update().filter(
            entreprise=facture.entreprise,
            id__in=requested.keys(),
        )
    }

    for produit_id, quantite_demandee in requested.items():
        produit = products.get(produit_id)
        if produit is None:
            raise WorkflowFacturationError("Le produit selectionne est invalide pour cette entreprise.")

        stock_disponible = int(produit.quantite_stock or 0)
        if quantite_demandee > stock_disponible:
            raise WorkflowFacturationError(
                f"Stock insuffisant pour le produit {produit.nom}. "
                f"Stock disponible : {stock_disponible}, quantite demandee : {quantite_demandee}."
            )

    for produit_id, quantite_demandee in requested.items():
        produit = products[produit_id]
        stock_avant = int(produit.quantite_stock or 0)
        produit.quantite_stock = stock_avant - quantite_demandee
        produit.save(update_fields=["quantite_stock"])
        _audit_stock_movement(
            facture=facture,
            produit=produit,
            quantite=quantite_demandee,
            stock_avant=stock_avant,
            stock_apres=produit.quantite_stock,
            user=user,
            action="stock_facture_decremente",
            description=f"Stock decremente apres emission de la facture {facture.numero}.",
        )

    _mark_facture_stock_state(facture=facture, applied=True)


def restore_stock_for_facture(*, facture, user):
    if not facture.stock_applique:
        return

    requested = _get_facture_product_quantities(facture)
    if not requested:
        _mark_facture_stock_state(facture=facture, applied=False)
        return

    products = {
        produit.id: produit
        for produit in Produit.objects.select_for_update().filter(
            entreprise=facture.entreprise,
            id__in=requested.keys(),
        )
    }

    for produit_id, quantite in requested.items():
        produit = products.get(produit_id)
        if produit is None:
            continue
        stock_avant = int(produit.quantite_stock or 0)
        produit.quantite_stock = stock_avant + quantite
        produit.save(update_fields=["quantite_stock"])
        _audit_stock_movement(
            facture=facture,
            produit=produit,
            quantite=quantite,
            stock_avant=stock_avant,
            stock_apres=produit.quantite_stock,
            user=user,
            action="stock_facture_restaure",
            description=f"Stock restaure apres annulation de la facture {facture.numero}.",
        )

    _mark_facture_stock_state(facture=facture, applied=False)


def assert_facture_editable(facture):
    if facture.statut != Facture.Statut.BROUILLON:
        raise WorkflowFacturationError("Seules les factures en brouillon peuvent etre modifiees.")
    if facture.paye or facture.statut == Facture.Statut.PAYEE:
        raise WorkflowFacturationError("Une facture payee ne peut pas etre modifiee.")


@transaction.atomic
def create_facture(*, entreprise, user, client_id=None, client_nom="", tva=0, remise=0, rabais=0, ristourne=0, lignes=None):
    if not user_has_permission(user, "billing.manage"):
        raise PermissionFacturationError("Seuls les proprietaires et gestionnaires peuvent creer une facture.")

    lignes = lignes or []
    client = None
    if client_id:
        client = get_object_or_404(Client, id=client_id, entreprise=entreprise)

    prepared_lignes = _build_lignes_payload(entreprise=entreprise, lignes=lignes)
    _ensure_stock_available(entreprise=entreprise, lignes=prepared_lignes)

    facture = Facture.objects.create(
        client=client,
        client_nom=client_nom,
        tva=Decimal(tva or 0),
        remise=Decimal(remise or 0),
        rabais=Decimal(rabais or 0),
        ristourne=Decimal(ristourne or 0),
        montant=0,
        description="",
        entreprise=entreprise,
    )

    total = Decimal("0")
    lignes_valides = 0

    for ligne in prepared_lignes:
        LigneFacture.objects.create(
            facture=facture,
            produit=ligne["produit"],
            service=ligne["service"],
            designation=ligne["designation"],
            quantite=ligne["quantite"],
            prix_unitaire=ligne["prix_unitaire"],
            tva=facture.tva,
        )
        total += Decimal(ligne["quantite"]) * ligne["prix_unitaire"]
        lignes_valides += 1

    facture.montant = total
    facture.save(update_fields=["montant"])

    if facture.total_net > Decimal("0"):
        apply_stock_for_facture(facture=facture, user=user)
        facture.changer_statut(Facture.Statut.EMISE, user=user, note="Facture validee apres creation.")
        comptabiliser_facture_emise(facture)

    facture.log_action(
        action=FactureHistorique.Action.CREATION,
        user=user,
        description=f"Facture {facture.numero} creee pour {facture.client_display}.",
        metadata={"lignes": lignes_valides},
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=user,
        action="facture_creee",
        module="billing",
        objet_type="Facture",
        objet_id=facture.id,
        description=f"Facture {facture.numero} creee pour {facture.client_display}.",
        metadata={"numero": facture.numero, "client": facture.client_display, "lignes": lignes_valides},
    )
    logger.info("Facture creee", extra={"entreprise_id": entreprise.id, "facture_id": facture.id, "user_id": user.id})
    return facture


@transaction.atomic
def update_facture(*, facture, user, client_id=None, client_nom="", tva=0, remise=0, rabais=0, ristourne=0, lignes=None):
    if not user_has_permission(user, "billing.manage"):
        raise PermissionFacturationError("Seuls les proprietaires et gestionnaires peuvent modifier une facture.")

    assert_facture_editable(facture)
    lignes = lignes or []
    prepared_lignes = _build_lignes_payload(entreprise=facture.entreprise, lignes=lignes)
    _ensure_stock_available(entreprise=facture.entreprise, lignes=prepared_lignes)

    client = None
    if client_id:
        client = get_object_or_404(Client, id=client_id, entreprise=facture.entreprise)

    facture.client = client
    facture.client_nom = client_nom
    facture.tva = Decimal(tva or 0)
    facture.remise = Decimal(remise or 0)
    facture.rabais = Decimal(rabais or 0)
    facture.ristourne = Decimal(ristourne or 0)
    facture.save(update_fields=["client", "client_nom", "tva", "remise", "rabais", "ristourne"])

    facture.lignes.all().delete()

    total = Decimal("0")
    lignes_valides = 0

    for ligne in prepared_lignes:
        LigneFacture.objects.create(
            facture=facture,
            produit=ligne["produit"],
            service=ligne["service"],
            designation=ligne["designation"],
            quantite=ligne["quantite"],
            prix_unitaire=ligne["prix_unitaire"],
            tva=facture.tva,
        )
        total += Decimal(ligne["quantite"]) * ligne["prix_unitaire"]
        lignes_valides += 1

    facture.montant = total
    facture.save(update_fields=["montant"])
    facture.log_action(
        action=FactureHistorique.Action.MODIFICATION,
        user=user,
        description=f"Facture {facture.numero} modifiee.",
        metadata={"lignes": lignes_valides},
    )
    logger.info("Facture modifiee", extra={"entreprise_id": facture.entreprise_id, "facture_id": facture.id, "user_id": user.id})
    return facture


@transaction.atomic
def change_facture_status(*, facture, nouveau_statut, user, note=""):
    if not user_has_permission(user, "billing.manage"):
        raise PermissionFacturationError("Seuls les proprietaires et gestionnaires peuvent changer le statut.")

    if facture.statut == Facture.Statut.PAYEE and nouveau_statut != Facture.Statut.PAYEE:
        raise WorkflowFacturationError("Une facture deja payee ne peut plus etre modifiee.")

    if nouveau_statut not in dict(Facture.Statut.choices):
        raise WorkflowFacturationError("Le statut demande est invalide.")

    ancien_statut = facture.statut

    if nouveau_statut in {Facture.Statut.EMISE, Facture.Statut.PAYEE} and ancien_statut == Facture.Statut.BROUILLON:
        apply_stock_for_facture(facture=facture, user=user)

    try:
        facture.changer_statut(nouveau_statut, user=user, note=note)
    except ValueError as exc:
        raise WorkflowFacturationError(str(exc)) from exc

    if nouveau_statut == Facture.Statut.ANNULEE:
        restore_stock_for_facture(facture=facture, user=user)

    if nouveau_statut in {Facture.Statut.EMISE, Facture.Statut.PAYEE}:
        comptabiliser_facture_emise(facture)

    logger.info(
        "Statut facture modifie",
        extra={"entreprise_id": facture.entreprise_id, "facture_id": facture.id, "user_id": user.id, "statut": nouveau_statut},
    )
    return facture


@transaction.atomic
def register_payment(*, facture, montant, mode, user, reference="", note=""):
    if not user_has_permission(user, "billing.payments"):
        raise PermissionFacturationError("Seuls les proprietaires et comptables peuvent enregistrer un paiement.")

    if facture.statut == Facture.Statut.ANNULEE:
        raise PaiementFacturationError("Impossible d'enregistrer un paiement sur une facture annulee.")
    if facture.statut == Facture.Statut.BROUILLON:
        raise PaiementFacturationError("Une facture brouillon doit etre emise avant de recevoir un paiement.")
    if facture.statut == Facture.Statut.PAYEE or facture.reste_a_payer <= Decimal("0"):
        raise PaiementFacturationError("Cette facture est deja soldée.")

    montant = Decimal(montant or 0)
    if montant <= Decimal("0"):
        raise PaiementFacturationError("Le montant du paiement doit etre strictement positif.")
    if montant > facture.reste_a_payer:
        raise PaiementFacturationError("Le paiement ne peut pas etre superieur au reste a payer.")
    if mode not in dict(PaiementFacture.ModePaiement.choices):
        raise PaiementFacturationError("Le mode de paiement est invalide.")

    paiement = PaiementFacture.objects.create(
        facture=facture,
        entreprise=facture.entreprise,
        montant=montant,
        mode=mode or PaiementFacture.ModePaiement.ESPECES,
        reference=reference,
        note=note,
    )
    facture.refresh_from_db()
    comptabiliser_paiement_facture(paiement)

    logger.info(
        "Paiement facture enregistre",
        extra={"entreprise_id": facture.entreprise_id, "facture_id": facture.id, "paiement_id": paiement.id, "user_id": user.id},
    )
    record_audit_event(
        entreprise=facture.entreprise,
        utilisateur=user,
        action="facture_payee",
        module="billing",
        objet_type="PaiementFacture",
        objet_id=paiement.id,
        description=f"Paiement enregistre sur la facture {facture.numero}.",
        metadata={"facture_id": facture.id, "facture_numero": facture.numero, "montant": str(paiement.montant), "mode": paiement.mode},
    )
    return paiement


@transaction.atomic
def delete_facture(*, facture, user):
    if getattr(user, "role", None) not in {"admin", "gestionnaire"}:
        raise PermissionFacturationError("Seuls les administrateurs et gestionnaires peuvent supprimer une facture.")
    if facture.statut == Facture.Statut.PAYEE or facture.paye:
        raise WorkflowFacturationError("Une facture payee ne peut pas etre supprimee.")
    assert_facture_editable(facture)
    facture_id = facture.id
    entreprise_id = facture.entreprise_id
    facture.delete()
    logger.info("Facture supprimee", extra={"entreprise_id": entreprise_id, "facture_id": facture_id, "user_id": user.id})


def list_services_for_entreprise(entreprise):
    return get_services_by_entreprise(entreprise)


def list_clients_for_entreprise(entreprise):
    from ..selectors.billing import get_clients_for_billing_by_entreprise

    return get_clients_for_billing_by_entreprise(entreprise)


def get_facture_for_enterprise(entreprise, facture_id):
    return get_facture_by_entreprise(entreprise, facture_id)


def list_factures_for_entreprise(entreprise, *, client_id=None, statut=None, search=None, date_debut=None, date_fin=None):
    return get_factures_by_entreprise(
        entreprise,
        client_id=client_id,
        statut=statut,
        search=search,
        date_debut=date_debut,
        date_fin=date_fin,
    )


def get_invoice_display_number(sequence_value, facture_date):
    number_format = getattr(settings, "JOATHAM_FACTURE_NUMBER_FORMAT", "standard")
    if number_format == "yearly":
        return f"F-{facture_date.year}-{sequence_value:04d}"
    return f"F-{sequence_value:04d}"
