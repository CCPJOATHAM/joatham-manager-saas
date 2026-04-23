from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone


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


def get_subscription_access_state(entreprise, *, user=None, as_of=None, allow_trial=True):
    if user is not None and getattr(user, "is_super_admin", False):
        return {
            "allowed": True,
            "reason": None,
            "subscription": None,
        }

    if entreprise is None:
        return {
            "allowed": False,
            "reason": "missing_entreprise",
            "subscription": None,
        }

    from core.models import Abonnement as CoreAbonnement
    from core.selectors.subscriptions import get_subscription_with_plan_for_entreprise

    subscription = get_subscription_with_plan_for_entreprise(entreprise)
    if subscription is None:
        return {
            "allowed": False,
            "reason": "missing_subscription",
            "subscription": None,
        }

    as_of = as_of or timezone.localdate()
    if not subscription.actif:
        return {
            "allowed": False,
            "reason": "inactive_subscription",
            "subscription": subscription,
        }

    if not subscription.date_fin or subscription.date_fin < as_of:
        return {
            "allowed": False,
            "reason": "expired_subscription",
            "subscription": subscription,
        }

    allowed_statuses = {CoreAbonnement.Statut.ACTIF}
    if allow_trial:
        allowed_statuses.add(CoreAbonnement.Statut.ESSAI)

    if subscription.statut not in allowed_statuses:
        return {
            "allowed": False,
            "reason": "active_subscription_required" if not allow_trial else "subscription_not_eligible",
            "subscription": subscription,
        }

    return {
        "allowed": True,
        "reason": None,
        "subscription": subscription,
    }


def ensure_subscription_access_for_entreprise(entreprise, *, user=None, as_of=None, allow_trial=True):
    state = get_subscription_access_state(
        entreprise,
        user=user,
        as_of=as_of,
        allow_trial=allow_trial,
    )
    if not state["allowed"]:
        raise PermissionDenied("L'abonnement de cette entreprise ne permet pas cet acces.")
    return state["subscription"]
