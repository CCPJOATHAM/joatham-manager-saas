from decimal import Decimal

from core.services.tenancy import get_object_for_entreprise, scope_queryset_to_entreprise

from ..models import Apprenant, Formation, InscriptionFormation, PaiementInscription


def get_apprenants_by_entreprise(entreprise):
    return scope_queryset_to_entreprise(Apprenant.objects.all(), entreprise).order_by("nom", "prenom", "id")


def get_formations_by_entreprise(entreprise):
    return scope_queryset_to_entreprise(Formation.objects.all(), entreprise).order_by("nom", "id")


def get_inscriptions_by_entreprise(entreprise):
    return (
        scope_queryset_to_entreprise(
            InscriptionFormation.objects.select_related("apprenant", "formation", "facture").prefetch_related("paiements"),
            entreprise,
        )
        .order_by("-date_inscription", "-id")
    )


def get_filtered_inscriptions_by_entreprise(entreprise, *, formation_id=None, statut=None, apprenant_id=None):
    queryset = get_inscriptions_by_entreprise(entreprise)
    if formation_id:
        queryset = queryset.filter(formation_id=formation_id)
    if statut:
        queryset = queryset.filter(statut=statut)
    if apprenant_id:
        queryset = queryset.filter(apprenant_id=apprenant_id)
    return queryset


def get_formation_by_entreprise(entreprise, formation_id):
    return get_object_for_entreprise(Formation.objects.all(), entreprise, id=formation_id)


def get_inscription_by_entreprise(entreprise, inscription_id):
    return get_object_for_entreprise(
        InscriptionFormation.objects.select_related("apprenant", "formation", "facture").prefetch_related("paiements"),
        entreprise,
        id=inscription_id,
    )


def get_paiements_by_inscription(entreprise, inscription):
    return (
        scope_queryset_to_entreprise(
            PaiementInscription.objects.select_related("inscription", "utilisateur"),
            entreprise,
        )
        .filter(inscription=inscription)
        .order_by("-date_paiement", "-date_creation", "-id")
    )


def get_paiement_by_inscription(entreprise, inscription, paiement_id):
    return get_object_for_entreprise(
        PaiementInscription.objects.select_related(
            "inscription",
            "inscription__apprenant",
            "inscription__formation",
            "utilisateur",
        ),
        entreprise,
        id=paiement_id,
        inscription=inscription,
    )


def get_paiement_documents_by_id(inscription):
    montant_prevu = Decimal(inscription.montant_prevu or 0)
    montant_paye_cumule = Decimal("0.00")
    documents_by_id = {}

    paiements = inscription.paiements.select_related("utilisateur").order_by(
        "date_paiement",
        "date_creation",
        "id",
    )
    for paiement in paiements:
        montant_paye_cumule += Decimal(paiement.montant or 0)
        solde_restant = max(montant_prevu - montant_paye_cumule, Decimal("0.00"))
        trop_percu = max(montant_paye_cumule - montant_prevu, Decimal("0.00"))
        document_type = "quittance" if solde_restant <= Decimal("0.00") and montant_paye_cumule >= montant_prevu else "recu"
        document_title = "Quittance de paiement" if document_type == "quittance" else "Reçu de paiement"
        documents_by_id[paiement.id] = {
            "document_type": document_type,
            "document_title": document_title,
            "document_action_label": "Télécharger la quittance" if document_type == "quittance" else "Télécharger le reçu",
            "montant_paye_cumule": montant_paye_cumule,
            "solde_restant": solde_restant,
            "trop_percu": trop_percu,
        }
    return documents_by_id


def enrich_paiements_with_document_data(inscription, paiements):
    documents_by_id = get_paiement_documents_by_id(inscription)
    enriched_paiements = list(paiements)
    for paiement in enriched_paiements:
        document = documents_by_id.get(paiement.id)
        if document is None:
            continue
        paiement.document_type = document["document_type"]
        paiement.document_title = document["document_title"]
        paiement.document_action_label = document["document_action_label"]
        paiement.montant_paye_cumule = document["montant_paye_cumule"]
        paiement.solde_restant_apres_paiement = document["solde_restant"]
        paiement.trop_percu_apres_paiement = document["trop_percu"]
    return enriched_paiements


def get_paiement_document_data(inscription, paiement):
    return get_paiement_documents_by_id(inscription).get(paiement.id)
