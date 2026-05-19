from core.services.tenancy import get_object_for_entreprise, scope_queryset_to_entreprise

from ..models import Employe, Poste, Presence


def get_postes_by_entreprise(entreprise, *, active_only=False):
    queryset = scope_queryset_to_entreprise(Poste.objects.all(), entreprise).order_by("nom", "id")
    if active_only:
        queryset = queryset.filter(actif=True)
    return queryset


def get_poste_by_entreprise(entreprise, poste_id):
    return get_object_for_entreprise(Poste.objects.all(), entreprise, id=poste_id)


def get_employes_by_entreprise(entreprise, *, active_only=False):
    queryset = (
        scope_queryset_to_entreprise(Employe.objects.select_related("poste"), entreprise)
        .order_by("nom", "prenom", "id")
    )
    if active_only:
        queryset = queryset.filter(actif=True)
    return queryset


def get_employe_by_entreprise(entreprise, employe_id):
    return get_object_for_entreprise(
        Employe.objects.select_related("poste"),
        entreprise,
        id=employe_id,
    )


def get_presences_by_entreprise(entreprise):
    return (
        scope_queryset_to_entreprise(Presence.objects.select_related("employe", "employe__poste"), entreprise)
        .order_by("-date", "employe__nom", "id")
    )
