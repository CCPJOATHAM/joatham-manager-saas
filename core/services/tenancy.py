from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404


def get_user_entreprise(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    return getattr(user, "entreprise", None)


def get_user_entreprise_or_raise(user):
    if getattr(user, "is_super_admin", False):
        raise PermissionDenied("Le super admin plateforme n'accede pas aux espaces entreprise.")
    entreprise = get_user_entreprise(user)
    if entreprise is None:
        raise PermissionDenied("Aucune entreprise n'est associee a cet utilisateur.")
    return entreprise


def scope_queryset_to_entreprise(queryset, entreprise, field_name="entreprise"):
    if entreprise is None:
        return queryset.none()
    return queryset.filter(**{field_name: entreprise})


def get_object_for_entreprise(queryset, entreprise, **lookup):
    scoped_queryset = scope_queryset_to_entreprise(queryset, entreprise)
    return get_object_or_404(scoped_queryset, **lookup)


def ensure_same_entreprise(instance, entreprise, field_name="entreprise"):
    if getattr(instance, f"{field_name}_id", None) != getattr(entreprise, "id", None):
        raise Http404("Objet introuvable.")
    return instance
