import logging
from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404

from core.audit import record_audit_event
from joatham_clients.models import Client
from joatham_users.permissions import user_has_permission

from ..exceptions import PermissionFacturationError, WorkflowFacturationError
from ..models import LigneProforma, Proforma
from .facturation import _build_lignes_payload, create_facture

logger = logging.getLogger(__name__)


def assert_proforma_editable(proforma):
    if proforma.statut in {Proforma.Statut.ANNULEE, Proforma.Statut.CONVERTIE}:
        raise WorkflowFacturationError("Une proforma annulee ou convertie ne peut plus etre modifiee.")


def assert_proforma_convertible(proforma):
    if proforma.facture_convertie_id or proforma.statut == Proforma.Statut.CONVERTIE:
        raise WorkflowFacturationError("Cette proforma a deja ete convertie en facture definitive.")
    if proforma.statut == Proforma.Statut.ANNULEE:
        raise WorkflowFacturationError("Une proforma annulee ne peut pas etre convertie.")


def _sync_proforma_lines(*, proforma, lignes):
    proforma.lignes.all().delete()
    total = Decimal("0")
    lignes_valides = 0

    for ligne in lignes:
        LigneProforma.objects.create(
            proforma=proforma,
            produit=ligne["produit"],
            service=ligne["service"],
            designation=ligne["designation"],
            quantite=ligne["quantite"],
            prix_unitaire=ligne["prix_unitaire"],
            tva=proforma.tva,
        )
        total += Decimal(ligne["quantite"]) * ligne["prix_unitaire"]
        lignes_valides += 1

    proforma.montant = total
    proforma.save(update_fields=["montant", "updated_at"])
    return lignes_valides


@transaction.atomic
def create_proforma(
    *,
    entreprise,
    user,
    client_id=None,
    client_nom="",
    tva=0,
    remise=0,
    rabais=0,
    ristourne=0,
    date_validite=None,
    notes="",
    conditions="",
    lignes=None,
):
    if not user_has_permission(user, "billing.manage"):
        raise PermissionFacturationError("Seuls les proprietaires et gestionnaires peuvent creer une proforma.")

    client = None
    if client_id:
        client = get_object_or_404(Client, id=client_id, entreprise=entreprise)

    prepared_lignes = _build_lignes_payload(entreprise=entreprise, lignes=lignes or [])
    proforma = Proforma.objects.create(
        entreprise=entreprise,
        client=client,
        client_nom=client_nom,
        tva=Decimal(tva or 0),
        remise=Decimal(remise or 0),
        rabais=Decimal(rabais or 0),
        ristourne=Decimal(ristourne or 0),
        date_validite=date_validite,
        notes=notes,
        conditions=conditions,
        created_by=user,
    )
    lignes_valides = _sync_proforma_lines(proforma=proforma, lignes=prepared_lignes)

    record_audit_event(
        entreprise=entreprise,
        utilisateur=user,
        action="proforma_creee",
        module="billing",
        objet_type="Proforma",
        objet_id=proforma.id,
        description=f"Proforma {proforma.numero} creee pour {proforma.client_display}.",
        metadata={"numero": proforma.numero, "client": proforma.client_display, "lignes": lignes_valides},
    )
    logger.info("Proforma creee", extra={"entreprise_id": entreprise.id, "proforma_id": proforma.id, "user_id": user.id})
    return proforma


@transaction.atomic
def update_proforma(
    *,
    proforma,
    user,
    client_id=None,
    client_nom="",
    tva=0,
    remise=0,
    rabais=0,
    ristourne=0,
    date_validite=None,
    notes="",
    conditions="",
    lignes=None,
):
    if not user_has_permission(user, "billing.manage"):
        raise PermissionFacturationError("Seuls les proprietaires et gestionnaires peuvent modifier une proforma.")

    assert_proforma_editable(proforma)
    client = None
    if client_id:
        client = get_object_or_404(Client, id=client_id, entreprise=proforma.entreprise)

    prepared_lignes = _build_lignes_payload(entreprise=proforma.entreprise, lignes=lignes or [])
    proforma.client = client
    proforma.client_nom = client_nom
    proforma.tva = Decimal(tva or 0)
    proforma.remise = Decimal(remise or 0)
    proforma.rabais = Decimal(rabais or 0)
    proforma.ristourne = Decimal(ristourne or 0)
    proforma.date_validite = date_validite
    proforma.notes = notes
    proforma.conditions = conditions
    proforma.save(
        update_fields=[
            "client",
            "client_nom",
            "tva",
            "remise",
            "rabais",
            "ristourne",
            "date_validite",
            "notes",
            "conditions",
            "updated_at",
        ]
    )
    lignes_valides = _sync_proforma_lines(proforma=proforma, lignes=prepared_lignes)

    record_audit_event(
        entreprise=proforma.entreprise,
        utilisateur=user,
        action="proforma_modifiee",
        module="billing",
        objet_type="Proforma",
        objet_id=proforma.id,
        description=f"Proforma {proforma.numero} modifiee.",
        metadata={"numero": proforma.numero, "lignes": lignes_valides},
    )
    logger.info("Proforma modifiee", extra={"entreprise_id": proforma.entreprise_id, "proforma_id": proforma.id, "user_id": user.id})
    return proforma


@transaction.atomic
def cancel_proforma(*, proforma, user):
    if not user_has_permission(user, "billing.manage"):
        raise PermissionFacturationError("Seuls les proprietaires et gestionnaires peuvent annuler une proforma.")
    if proforma.statut == Proforma.Statut.CONVERTIE or proforma.facture_convertie_id:
        raise WorkflowFacturationError("Une proforma convertie ne peut plus etre annulee.")
    if proforma.statut == Proforma.Statut.ANNULEE:
        return proforma

    proforma.statut = Proforma.Statut.ANNULEE
    proforma.save(update_fields=["statut", "updated_at"])
    record_audit_event(
        entreprise=proforma.entreprise,
        utilisateur=user,
        action="proforma_annulee",
        module="billing",
        objet_type="Proforma",
        objet_id=proforma.id,
        description=f"Proforma {proforma.numero} annulee.",
        metadata={"numero": proforma.numero},
    )
    return proforma


def _build_facture_lines_from_proforma(proforma):
    lignes = []
    for ligne in proforma.lignes.all():
        lignes.append(
            {
                "designation": ligne.designation,
                "quantite": ligne.quantite,
                "prix": ligne.prix_unitaire,
                "product_id": str(ligne.produit_id) if ligne.produit_id else "",
                "service_id": str(ligne.service_id) if ligne.service_id else "",
            }
        )
    return lignes


@transaction.atomic
def convert_proforma_to_facture(*, proforma, user):
    if not user_has_permission(user, "billing.manage"):
        raise PermissionFacturationError("Seuls les proprietaires et gestionnaires peuvent convertir une proforma.")

    proforma = Proforma.objects.select_for_update().select_related("entreprise", "client", "facture_convertie").get(id=proforma.id)
    assert_proforma_convertible(proforma)

    facture = create_facture(
        entreprise=proforma.entreprise,
        user=user,
        client_id=proforma.client_id,
        client_nom=proforma.client_nom or "",
        tva=proforma.tva,
        remise=proforma.remise,
        rabais=proforma.rabais,
        ristourne=proforma.ristourne,
        lignes=_build_facture_lines_from_proforma(proforma),
    )

    proforma.facture_convertie = facture
    proforma.statut = Proforma.Statut.CONVERTIE
    proforma.save(update_fields=["facture_convertie", "statut", "updated_at"])
    record_audit_event(
        entreprise=proforma.entreprise,
        utilisateur=user,
        action="proforma_convertie",
        module="billing",
        objet_type="Proforma",
        objet_id=proforma.id,
        description=f"Proforma {proforma.numero} convertie en facture {facture.numero}.",
        metadata={"proforma": proforma.numero, "facture": facture.numero, "facture_id": facture.id},
    )
    logger.info(
        "Proforma convertie",
        extra={
            "entreprise_id": proforma.entreprise_id,
            "proforma_id": proforma.id,
            "facture_id": facture.id,
            "user_id": user.id,
        },
    )
    return facture
