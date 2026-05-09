from core.services.tenancy import get_object_for_entreprise, scope_queryset_to_entreprise

from ..models import SessionCaisse


def get_sessions_by_entreprise(entreprise, *, caisse=None, statut=None, date_debut=None, date_fin=None):
    queryset = scope_queryset_to_entreprise(SessionCaisse.objects.all(), entreprise).select_related(
        "caisse",
        "utilisateur_ouverture",
        "utilisateur_fermeture",
    )
    if caisse is not None:
        queryset = queryset.filter(caisse=caisse)
    if statut:
        queryset = queryset.filter(statut=statut)
    if date_debut:
        queryset = queryset.filter(date_ouverture__date__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(date_ouverture__date__lte=date_fin)
    return queryset.order_by("-date_ouverture", "-id")


def get_open_session_for_caisse(caisse):
    return (
        SessionCaisse.objects.filter(caisse=caisse, statut=SessionCaisse.Statut.OUVERTE)
        .select_related("caisse", "utilisateur_ouverture")
        .first()
    )


def get_session_by_entreprise(entreprise, session_id):
    return get_object_for_entreprise(
        SessionCaisse.objects.select_related("caisse", "utilisateur_ouverture", "utilisateur_fermeture"),
        entreprise,
        id=session_id,
    )
