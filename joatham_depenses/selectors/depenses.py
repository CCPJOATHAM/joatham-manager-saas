from core.services.tenancy import scope_queryset_to_entreprise

from ..models import Depense


def get_depenses_by_entreprise(entreprise):
    return scope_queryset_to_entreprise(Depense.objects.all(), entreprise).order_by("-date")
