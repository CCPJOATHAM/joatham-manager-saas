from decimal import Decimal

from django.db.models import Count, Sum

from .apprenants import get_filtered_inscriptions_by_entreprise, get_formations_by_entreprise
from ..models import Apprenant, Formation, InscriptionFormation


def get_apprenants_dashboard_data(entreprise, *, formation_id=None, statut=None):
    active_apprenants = Apprenant.objects.filter(entreprise=entreprise, actif=True).count()
    active_formations = Formation.objects.filter(entreprise=entreprise, actif=True).count()

    inscriptions = get_filtered_inscriptions_by_entreprise(
        entreprise,
        formation_id=formation_id,
        statut=statut,
    )

    aggregates = inscriptions.aggregate(
        total_inscriptions=Count("id"),
        total_du=Sum("montant_prevu"),
        total_paye=Sum("montant_paye"),
        total_restant=Sum("solde"),
    )

    total_du = aggregates["total_du"] or Decimal("0.00")
    total_paye = aggregates["total_paye"] or Decimal("0.00")
    total_restant = aggregates["total_restant"] or Decimal("0.00")

    status_breakdown = {
        item["statut"]: item["count"]
        for item in inscriptions.values("statut").annotate(count=Count("id")).order_by("statut")
    }

    recent_inscriptions = inscriptions.order_by("-date_inscription", "-id")[:10]
    overdue_inscriptions = inscriptions.filter(solde__gt=0).count()
    formations = get_formations_by_entreprise(entreprise).filter(actif=True)
    unpaid_inscriptions = inscriptions.filter(solde__gt=0)

    oldest_unpaid_inscriptions = unpaid_inscriptions.order_by("date_inscription", "id")[:5]
    largest_balance_learners = (
        unpaid_inscriptions.values("apprenant_id", "apprenant__nom", "apprenant__prenom")
        .annotate(total_solde=Sum("solde"), inscriptions_count=Count("id"))
        .order_by("-total_solde", "apprenant__nom", "apprenant__prenom")[:5]
    )
    largest_balance_formations = (
        unpaid_inscriptions.values("formation_id", "formation__nom")
        .annotate(total_solde=Sum("solde"), inscriptions_count=Count("id"))
        .order_by("-total_solde", "formation__nom")[:5]
    )
    active_unpaid_inscriptions = unpaid_inscriptions.filter(statut=InscriptionFormation.Statut.EN_COURS).order_by(
        "date_inscription", "id"
    )[:5]

    return {
        "kpis": {
            "active_apprenants": active_apprenants,
            "active_formations": active_formations,
            "total_inscriptions": aggregates["total_inscriptions"] or 0,
            "total_du": total_du,
            "total_paye": total_paye,
            "total_restant": total_restant,
            "overdue_inscriptions": overdue_inscriptions,
            "status_breakdown": status_breakdown,
        },
        "inscriptions": recent_inscriptions,
        "alerts": {
            "oldest_unpaid_inscriptions": oldest_unpaid_inscriptions,
            "largest_balance_learners": largest_balance_learners,
            "largest_balance_formations": largest_balance_formations,
            "active_unpaid_inscriptions": active_unpaid_inscriptions,
        },
        "formations": formations,
        "statuts": InscriptionFormation.Statut.choices,
        "selected_formation": str(formation_id or ""),
        "selected_statut": statut or "",
    }
