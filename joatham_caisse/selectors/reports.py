from decimal import Decimal

from django.db.models import Count, Q, Sum

from ..models import MouvementCaisse, SessionCaisse
from .mouvements import get_mouvements_for_entreprise
from .session import get_sessions_by_entreprise


ENTRY_TYPES = [
    MouvementCaisse.TypeMouvement.ENTREE,
    MouvementCaisse.TypeMouvement.PAIEMENT_FACTURE,
    MouvementCaisse.TypeMouvement.AJUSTEMENT,
]
EXIT_TYPES = [
    MouvementCaisse.TypeMouvement.SORTIE,
    MouvementCaisse.TypeMouvement.DEPENSE,
    MouvementCaisse.TypeMouvement.TRANSFERT,
]


def _coalesce_amount(value):
    return value if value is not None else Decimal("0.00")


def get_cash_report_snapshot(entreprise, *, caisse=None, date_debut=None, date_fin=None):
    movements = get_mouvements_for_entreprise(
        entreprise,
        caisse=caisse,
        date_debut=date_debut,
        date_fin=date_fin,
    )
    sessions = get_sessions_by_entreprise(
        entreprise,
        caisse=caisse,
        date_debut=date_debut,
        date_fin=date_fin,
    )

    movement_totals = movements.aggregate(
        total_entrees=Sum("montant", filter=Q(type_mouvement__in=ENTRY_TYPES)),
        total_sorties=Sum("montant", filter=Q(type_mouvement__in=EXIT_TYPES)),
        total_depenses_caisse=Sum(
            "montant",
            filter=Q(type_mouvement=MouvementCaisse.TypeMouvement.DEPENSE),
        ),
        total_paiements_factures=Sum(
            "montant",
            filter=Q(type_mouvement=MouvementCaisse.TypeMouvement.PAIEMENT_FACTURE),
        ),
        nombre_mouvements=Count("id"),
    )

    summary_by_caisse = []
    by_caisse_rows = (
        movements.values("caisse_id", "caisse__nom", "caisse__code", "caisse__devise")
        .annotate(
            mouvement_count=Count("id"),
            total_entrees=Sum("montant", filter=Q(type_mouvement__in=ENTRY_TYPES)),
            total_sorties=Sum("montant", filter=Q(type_mouvement__in=EXIT_TYPES)),
            total_depenses=Sum(
                "montant",
                filter=Q(type_mouvement=MouvementCaisse.TypeMouvement.DEPENSE),
            ),
            total_paiements=Sum(
                "montant",
                filter=Q(type_mouvement=MouvementCaisse.TypeMouvement.PAIEMENT_FACTURE),
            ),
        )
        .order_by("caisse__nom", "caisse_id")
    )
    for row in by_caisse_rows:
        total_entrees = _coalesce_amount(row.get("total_entrees"))
        total_sorties = _coalesce_amount(row.get("total_sorties"))
        summary_by_caisse.append(
            {
                "caisse_id": row["caisse_id"],
                "nom": row["caisse__nom"],
                "code": row["caisse__code"],
                "devise": row["caisse__devise"],
                "mouvement_count": row["mouvement_count"],
                "total_entrees": total_entrees,
                "total_sorties": total_sorties,
                "total_depenses": _coalesce_amount(row.get("total_depenses")),
                "total_paiements": _coalesce_amount(row.get("total_paiements")),
                "solde_net": total_entrees - total_sorties,
            }
        )

    type_labels = dict(MouvementCaisse.TypeMouvement.choices)
    summary_by_type = [
        {
            "type_mouvement": row["type_mouvement"],
            "label": type_labels.get(row["type_mouvement"], row["type_mouvement"]),
            "count": row["count"],
            "total": _coalesce_amount(row["total"]),
        }
        for row in movements.values("type_mouvement")
        .annotate(count=Count("id"), total=Sum("montant"))
        .order_by("type_mouvement")
    ]

    return {
        "total_entrees": _coalesce_amount(movement_totals.get("total_entrees")),
        "total_sorties": _coalesce_amount(movement_totals.get("total_sorties")),
        "total_depenses_caisse": _coalesce_amount(movement_totals.get("total_depenses_caisse")),
        "total_paiements_factures": _coalesce_amount(movement_totals.get("total_paiements_factures")),
        "solde_net": _coalesce_amount(movement_totals.get("total_entrees"))
        - _coalesce_amount(movement_totals.get("total_sorties")),
        "nombre_mouvements": movement_totals.get("nombre_mouvements") or 0,
        "sessions_ouvertes": sessions.filter(statut=SessionCaisse.Statut.OUVERTE).count(),
        "sessions_fermees": sessions.filter(statut=SessionCaisse.Statut.FERMEE).count(),
        "sessions_validees": sessions.filter(statut=SessionCaisse.Statut.VALIDEE).count(),
        "ecarts_positifs": sessions.filter(ecart__gt=0).count(),
        "ecarts_negatifs": sessions.filter(ecart__lt=0).count(),
        "summary_by_caisse": summary_by_caisse,
        "summary_by_type": summary_by_type,
    }


def get_movement_totals_for_period(entreprise, *, start_date, end_date):
    return (
        MouvementCaisse.objects.filter(
            entreprise=entreprise,
            date_mouvement__gte=start_date,
            date_mouvement__lt=end_date,
        )
        .values("type_mouvement")
        .annotate(total=Sum("montant"))
        .order_by("type_mouvement")
    )
