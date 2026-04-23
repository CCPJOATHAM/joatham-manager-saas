from datetime import date
from decimal import Decimal

from django.db.models import Sum

from core.models import ActivityLog
from joatham_billing.selectors.billing import get_factures_by_entreprise
from joatham_clients.selectors.clients import get_clients_by_entreprise
from joatham_depenses.selectors.depenses import get_depenses_by_entreprise
from joatham_apprenants.models import Apprenant
from joatham_products.selectors.products import get_products_by_entreprise


def get_dashboard_kpis_by_entreprise(entreprise):
    today = date.today()
    factures = get_factures_by_entreprise(entreprise)
    depenses = get_depenses_by_entreprise(entreprise)
    clients = get_clients_by_entreprise(entreprise)

    total_ca = factures.aggregate(Sum("montant"))["montant__sum"] or Decimal("0")
    total_depenses = depenses.aggregate(Sum("montant"))["montant__sum"] or Decimal("0")
    total_jour = factures.filter(date__date=today).aggregate(Sum("montant"))["montant__sum"] or Decimal("0")
    total_mois = factures.filter(date__year=today.year, date__month=today.month).aggregate(Sum("montant"))["montant__sum"] or Decimal("0")
    depense_jour = depenses.filter(date__date=today).aggregate(Sum("montant"))["montant__sum"] or Decimal("0")
    depense_mois = depenses.filter(date__year=today.year, date__month=today.month).aggregate(Sum("montant"))["montant__sum"] or Decimal("0")
    payees = factures.filter(paye=True).count()
    impayees = factures.filter(paye=False).count()
    total_encaisse = sum((Decimal(facture.total_paye or 0) for facture in factures), Decimal("0"))
    reste_encaisser = sum((Decimal(facture.reste_a_payer or 0) for facture in factures), Decimal("0"))
    total_tva = sum((Decimal(facture.montant or 0) * Decimal(facture.tva or 0) / Decimal("100") for facture in factures), Decimal("0"))
    nombre_apprenants = Apprenant.objects.filter(entreprise=entreprise, actif=True).count()
    recent_activity = ActivityLog.objects.filter(entreprise=entreprise).select_related("utilisateur")[:6]
    flow_activity = (
        ActivityLog.objects.filter(
            entreprise=entreprise,
            module__in=["billing", "depenses", "apprenants"],
            utilisateur__isnull=False,
        )
        .select_related("utilisateur")[:6]
    )
    products = get_products_by_entreprise(entreprise)
    rupture_products = list(products.filter(quantite_stock__lte=0)[:5])
    low_stock_products = list(products.filter(quantite_stock__gt=0, quantite_stock__lte=F("seuil_alerte"))[:5])

    return {
        "total_ca": total_ca,
        "total_depenses": total_depenses,
        "benefice": total_ca - total_depenses,
        "total_jour": total_jour,
        "total_mois": total_mois,
        "depense_jour": depense_jour,
        "depense_mois": depense_mois,
        "total_tva": total_tva,
        "payees": payees,
        "impayees": impayees,
        "total_encaisse": total_encaisse,
        "reste_encaisser": reste_encaisser,
        "nombre_factures": factures.count(),
        "nombre_clients": clients.count(),
        "nombre_apprenants": nombre_apprenants,
        "labels": ["Payees", "Impayees"],
        "data": [payees, impayees],
        "recent_activity": recent_activity,
        "flow_activity": flow_activity,
        "rupture_products_count": products.filter(quantite_stock__lte=0).count(),
        "low_stock_products_count": products.filter(quantite_stock__gt=0, quantite_stock__lte=F("seuil_alerte")).count(),
        "rupture_products": rupture_products,
        "low_stock_products": low_stock_products,
    }


from django.db.models import F  # noqa: E402
