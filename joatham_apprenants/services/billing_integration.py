from django.utils.translation import gettext_lazy
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from core.audit import record_audit_event
from core.services.tenancy import ensure_same_entreprise, get_object_for_entreprise
from joatham_billing.models import Facture
from joatham_billing.services.facturation import create_facture
from joatham_users.permissions import require_permission

from ..models import InscriptionFormation


@transaction.atomic
def generate_facture_for_inscription(*, entreprise, inscription_id, utilisateur):
    require_permission(utilisateur, "apprenants.manage")
    require_permission(utilisateur, "billing.manage")

    inscription = get_object_for_entreprise(
        InscriptionFormation.objects.select_related("apprenant", "formation", "facture"),
        entreprise,
        id=inscription_id,
    )
    ensure_same_entreprise(inscription, entreprise)

    if inscription.facture_id:
        raise ValidationError(gettext_lazy('Cette inscription est déjà liée à une facture.'))

    apprenant_label = str(inscription.apprenant)
    formation = inscription.formation
    montant = Decimal(str(inscription.montant_prevu or formation.prix or 0))

    facture = create_facture(
        entreprise=entreprise,
        user=utilisateur,
        client_nom=apprenant_label,
        tva=0,
        lignes=[
            {
                "designation": f"Inscription formation - {formation.nom}",
                "quantite": 1,
                "prix": montant,
            }
        ],
    )

    inscription.facture = facture
    inscription.save(update_fields=["facture"])

    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="facture_inscription_creee",
        module="apprenants",
        objet_type="InscriptionFormation",
        objet_id=inscription.id,
        description=f"Facture {facture.numero} creee pour l'inscription {inscription.id}.",
        metadata={
            "inscription_id": inscription.id,
            "facture_id": facture.id,
            "facture_numero": facture.numero,
            "formation": formation.nom,
            "apprenant": apprenant_label,
        },
    )
    return facture


@transaction.atomic
def link_facture_to_inscription(*, entreprise, inscription_id, facture_id, utilisateur):
    require_permission(utilisateur, "apprenants.manage")
    require_permission(utilisateur, "billing.manage")

    inscription = get_object_for_entreprise(
        InscriptionFormation.objects.select_related("apprenant", "formation", "facture"),
        entreprise,
        id=inscription_id,
    )
    facture = get_object_for_entreprise(Facture.objects.all(), entreprise, id=facture_id)

    ensure_same_entreprise(inscription, entreprise)
    ensure_same_entreprise(facture, entreprise)

    if inscription.facture_id == facture.id:
        return facture
    if inscription.facture_id:
        raise ValidationError(gettext_lazy('Cette inscription est déjà liée à une autre facture.'))

    if facture.inscriptions_formations.exclude(id=inscription.id).exists():
        raise ValidationError(gettext_lazy('Cette facture est déjà liée à une autre inscription.'))

    inscription.facture = facture
    inscription.save(update_fields=["facture"])

    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="facture_existante_liee_inscription",
        module="apprenants",
        objet_type="InscriptionFormation",
        objet_id=inscription.id,
        description=f"Facture existante {facture.numero} liee a l'inscription {inscription.id}.",
        metadata={
            "inscription_id": inscription.id,
            "facture_id": facture.id,
            "facture_numero": facture.numero,
        },
    )
    return facture


@transaction.atomic
def unlink_facture_from_inscription(*, entreprise, inscription_id, facture_id, utilisateur):
    require_permission(utilisateur, "apprenants.manage")
    require_permission(utilisateur, "billing.manage")

    inscription = get_object_for_entreprise(
        InscriptionFormation.objects.select_related("apprenant", "formation", "facture"),
        entreprise,
        id=inscription_id,
    )
    facture = get_object_for_entreprise(Facture.objects.prefetch_related("paiements"), entreprise, id=facture_id)

    ensure_same_entreprise(inscription, entreprise)
    ensure_same_entreprise(facture, entreprise)

    if not inscription.facture_id:
        raise ValidationError(gettext_lazy("Aucune facture n'est liée à cette inscription."))
    if inscription.facture_id != facture.id:
        raise ValidationError(gettext_lazy('La facture demandée ne correspond pas à la facture liée à cette inscription.'))
    if facture.paiements.exists():
        raise ValidationError(gettext_lazy('Impossible de délier une facture qui comporte déjà des paiements.'))
    if facture.paye or facture.statut == Facture.Statut.PAYEE:
        raise ValidationError(gettext_lazy('Impossible de délier une facture déjà payée.'))
    if facture.statut not in {Facture.Statut.BROUILLON, Facture.Statut.EMISE}:
        raise ValidationError(gettext_lazy('Impossible de délier cette facture dans son état actuel.'))

    origine_liaison = "inconnue"
    last_link_event = (
        inscription.entreprise.activity_logs.filter(
            module="apprenants",
            objet_type="InscriptionFormation",
            objet_id=inscription.id,
            action__in=["facture_inscription_creee", "facture_existante_liee_inscription"],
        )
        .order_by("-date_creation", "-id")
        .first()
    )
    if last_link_event:
        origine_liaison = {
            "facture_inscription_creee": "cree_depuis_inscription",
            "facture_existante_liee_inscription": "liee_manuellement",
        }.get(last_link_event.action, "inconnue")

    inscription.facture = None
    inscription.save(update_fields=["facture"])

    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="facture_deliee_inscription",
        module="apprenants",
        objet_type="InscriptionFormation",
        objet_id=inscription.id,
        description=f"Facture {facture.numero} deliee de l'inscription {inscription.id}.",
        metadata={
            "inscription_id": inscription.id,
            "facture_id": facture.id,
            "facture_numero": facture.numero,
            "origine_liaison": origine_liaison,
        },
    )
    return facture
