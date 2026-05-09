from core.services.tenancy import get_object_for_entreprise, scope_queryset_to_entreprise

from ..models import Caisse


def get_caisses_by_entreprise(entreprise):
    return scope_queryset_to_entreprise(Caisse.objects.all(), entreprise).select_related("cree_par").order_by("nom", "id")


def get_caisse_by_entreprise(entreprise, caisse_id):
    return get_object_for_entreprise(Caisse.objects.select_related("cree_par"), entreprise, id=caisse_id)


def get_active_caisse_by_code(entreprise, code):
    return (
        scope_queryset_to_entreprise(Caisse.objects.all(), entreprise)
        .filter(code=(code or "").strip(), est_active=True)
        .select_related("cree_par")
        .first()
    )
