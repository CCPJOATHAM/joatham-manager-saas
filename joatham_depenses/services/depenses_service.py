from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from core.audit import record_audit_event

from ..selectors.depenses import get_depenses_by_entreprise


def list_depenses_for_entreprise(entreprise, *, date_debut=None, date_fin=None, recherche=None):
    queryset = get_depenses_by_entreprise(entreprise)
    if date_debut and date_fin:
        queryset = queryset.filter(date__date__range=[date_debut, date_fin])
    if recherche:
        queryset = queryset.filter(description__icontains=recherche)
    return queryset


def create_depense_for_entreprise(form, entreprise, utilisateur=None):
    depense = form.save(commit=False)
    depense.entreprise = entreprise
    depense.save()
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="depense_creee",
        module="depenses",
        objet_type="Depense",
        objet_id=depense.id,
        description=f"Depense creee: {depense.description}.",
        metadata={"montant": str(depense.montant)},
    )
    return depense


def get_depenses_total(queryset):
    return queryset.aggregate(Sum("montant"))["montant__sum"] or 0


def get_depenses_kpis(entreprise):
    queryset = get_depenses_by_entreprise(entreprise)
    today = timezone.localdate()
    month_start = today.replace(day=1)
    previous_month_end = month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)

    total = get_depenses_total(queryset)
    today_total = get_depenses_total(queryset.filter(date__date=today))
    month_total = get_depenses_total(queryset.filter(date__date__gte=month_start, date__date__lte=today))
    previous_month_total = get_depenses_total(
        queryset.filter(date__date__gte=previous_month_start, date__date__lte=previous_month_end)
    )
    count = queryset.count()
    average = (total / count) if count else 0

    if previous_month_total:
        evolution_percent = ((month_total - previous_month_total) / previous_month_total) * 100
        evolution_direction = "up" if evolution_percent >= 0 else "down"
        evolution_display = f"{evolution_percent:+.1f}%".replace(".", ",")
    elif month_total:
        evolution_percent = None
        evolution_direction = "up"
        evolution_display = "Nouveau"
    else:
        evolution_percent = 0
        evolution_direction = "flat"
        evolution_display = "0,0%"

    return {
        "count": count,
        "total": total,
        "today_total": today_total,
        "month_total": month_total,
        "average": average,
        "evolution_percent": evolution_percent,
        "evolution_direction": evolution_direction,
        "evolution_display": evolution_display,
    }
