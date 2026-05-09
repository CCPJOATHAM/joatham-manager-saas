from django.db.models import Q, Sum

from core.services.tenancy import scope_queryset_to_entreprise

from ..models import MouvementCaisse


def get_mouvements_for_session(session):
    return (
        MouvementCaisse.objects.filter(session=session)
        .select_related("caisse", "session", "cree_par")
        .order_by("-date_mouvement", "-id")
    )


def get_total_mouvements_for_session(session):
    return MouvementCaisse.objects.filter(session=session).aggregate(total=Sum("montant")).get("total")


def get_mouvements_for_entreprise(entreprise, *, caisse=None, session=None, date_debut=None, date_fin=None):
    queryset = scope_queryset_to_entreprise(MouvementCaisse.objects.all(), entreprise).select_related(
        "caisse",
        "session",
        "cree_par",
    )
    if caisse is not None:
        queryset = queryset.filter(caisse=caisse)
    if session is not None:
        queryset = queryset.filter(session=session)
    if date_debut:
        queryset = queryset.filter(date_mouvement__date__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(date_mouvement__date__lte=date_fin)
    return queryset.order_by("-date_mouvement", "-id")


def get_cash_flow_totals_for_session(session):
    totals = MouvementCaisse.objects.filter(session=session, statut=MouvementCaisse.Statut.CONFIRME).aggregate(
        total_entrees=Sum(
            "montant",
            filter=Q(
                type_mouvement__in=[
                    MouvementCaisse.TypeMouvement.ENTREE,
                    MouvementCaisse.TypeMouvement.PAIEMENT_FACTURE,
                    MouvementCaisse.TypeMouvement.AJUSTEMENT,
                ]
            ),
        ),
        total_sorties=Sum(
            "montant",
            filter=Q(
                type_mouvement__in=[
                    MouvementCaisse.TypeMouvement.SORTIE,
                    MouvementCaisse.TypeMouvement.DEPENSE,
                    MouvementCaisse.TypeMouvement.TRANSFERT,
                ]
            ),
        ),
    )
    return {
        "total_entrees": totals.get("total_entrees") or 0,
        "total_sorties": totals.get("total_sorties") or 0,
    }
