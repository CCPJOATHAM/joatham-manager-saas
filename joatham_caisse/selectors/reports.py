from django.db.models import Sum

from ..models import MouvementCaisse


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

