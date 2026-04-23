from django.db.models import Q

from core.services.tenancy import scope_queryset_to_entreprise

from ..models import Client


def get_clients_by_entreprise(entreprise, *, search=None):
    queryset = scope_queryset_to_entreprise(Client.objects.all(), entreprise)
    if search:
        search = search.strip()
        queryset = queryset.filter(
            Q(nom__icontains=search)
            | Q(telephone__icontains=search)
            | Q(email__icontains=search)
        )
    return queryset.order_by("nom")
