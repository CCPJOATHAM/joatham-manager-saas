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
