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


def get_mouvements_for_entreprise(
    entreprise,
    *,
    caisse=None,
    session=None,
    type_mouvement=None,
    moyen_paiement=None,
    date_debut=None,
    date_fin=None,
    montant_min=None,
    montant_max=None,
    q=None,
):
    queryset = scope_queryset_to_entreprise(MouvementCaisse.objects.all(), entreprise).select_related(
        "caisse",
        "session",
        "cree_par",
    )
    if caisse is not None:
        queryset = queryset.filter(caisse=caisse)
    if session is not None:
        queryset = queryset.filter(session=session)
    if type_mouvement:
        queryset = queryset.filter(type_mouvement=type_mouvement)
    if moyen_paiement:
        queryset = queryset.filter(moyen_paiement=moyen_paiement)
    if date_debut:
        queryset = queryset.filter(date_mouvement__date__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(date_mouvement__date__lte=date_fin)
    if montant_min is not None:
        queryset = queryset.filter(montant__gte=montant_min)
    if montant_max is not None:
        queryset = queryset.filter(montant__lte=montant_max)
    if q:
        queryset = queryset.filter(Q(libelle__icontains=q) | Q(reference__icontains=q))
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
