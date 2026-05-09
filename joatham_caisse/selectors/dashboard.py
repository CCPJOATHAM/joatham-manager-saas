from django.db.models import Q, Sum
from django.utils import timezone

from ..models import Caisse, MouvementCaisse, SessionCaisse


def get_cash_dashboard_snapshot(entreprise):
    today = timezone.localdate()
    open_sessions_queryset = (
        SessionCaisse.objects.filter(
            entreprise=entreprise,
            statut=SessionCaisse.Statut.OUVERTE,
        )
        .select_related("caisse", "utilisateur_ouverture")
        .order_by("-date_ouverture", "-id")
    )
    movement_totals = MouvementCaisse.objects.filter(
        entreprise=entreprise,
        date_mouvement__date=today,
        statut=MouvementCaisse.Statut.CONFIRME,
    ).aggregate(
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
    open_sessions = list(open_sessions_queryset[:5])
    recent_movements = list(
        MouvementCaisse.objects.filter(
            entreprise=entreprise,
            statut=MouvementCaisse.Statut.CONFIRME,
        )
        .select_related("caisse", "session", "cree_par")
        .order_by("-date_mouvement", "-id")[:8]
    )
    return {
        "caisses_actives": Caisse.objects.filter(entreprise=entreprise, est_active=True).count(),
        "sessions_ouvertes": open_sessions_queryset.count(),
        "total_entrees_jour": movement_totals.get("total_entrees") or 0,
        "total_sorties_jour": movement_totals.get("total_sorties") or 0,
        "solde_theorique_ouvert": open_sessions_queryset.aggregate(total=Sum("solde_theorique")).get("total") or 0,
        "open_sessions": open_sessions,
        "recent_movements": recent_movements,
        "ecarts_recents": list(
            SessionCaisse.objects.filter(entreprise=entreprise)
            .exclude(ecart=0)
            .select_related("caisse")
            .order_by("-date_modification", "-id")[:5]
        ),
    }
