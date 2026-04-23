from core.services.tenancy import get_object_for_entreprise, scope_queryset_to_entreprise

from ..models import Produit


STOCK_FILTER_ALL = "all"
STOCK_FILTER_LOW = "stock_faible"
STOCK_FILTER_RUPTURE = "rupture"


def get_products_by_entreprise(entreprise, *, stock_filter=None):
    queryset = scope_queryset_to_entreprise(Produit.objects.all(), entreprise)

    if stock_filter == STOCK_FILTER_LOW:
        queryset = queryset.filter(quantite_stock__lte=models.F("seuil_alerte"))
    elif stock_filter == STOCK_FILTER_RUPTURE:
        queryset = queryset.filter(quantite_stock__lte=0)

    return queryset.order_by("nom", "id")


def get_product_by_entreprise(entreprise, product_id):
    return get_object_for_entreprise(Produit.objects.all(), entreprise, id=product_id)


def get_product_counts_by_entreprise(entreprise):
    queryset = scope_queryset_to_entreprise(Produit.objects.all(), entreprise)
    total = queryset.count()
    rupture = queryset.filter(quantite_stock__lte=0).count()
    stock_faible = queryset.filter(quantite_stock__lte=models.F("seuil_alerte")).count()
    actifs = queryset.filter(actif=True).count()
    return {
        "total": total,
        "rupture": rupture,
        "stock_faible": stock_faible,
        "actifs": actifs,
    }


# Django model expressions imported late to keep selectors compact.
from django.db import models  # noqa: E402
