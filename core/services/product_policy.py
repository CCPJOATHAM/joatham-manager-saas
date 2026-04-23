from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from core.services.subscription import get_current_subscription, is_subscription_expired, refresh_subscription_status
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.models import AbonnementEntreprise


ACCESS_FREE = "free"
ACCESS_TRIAL_OR_ACTIVE = "trial_or_active"
ACCESS_ACTIVE_ONLY = "active_only"


MODULE_ACCESS_POLICY = {
    "dashboard": ACCESS_TRIAL_OR_ACTIVE,
    "clients": ACCESS_TRIAL_OR_ACTIVE,
    "services": ACCESS_TRIAL_OR_ACTIVE,
    "expenses": ACCESS_TRIAL_OR_ACTIVE,
    "products": ACCESS_TRIAL_OR_ACTIVE,
    "billing": ACCESS_TRIAL_OR_ACTIVE,
    "accounting": ACCESS_ACTIVE_ONLY,
    "apprenants": ACCESS_TRIAL_OR_ACTIVE,
    "users": ACCESS_TRIAL_OR_ACTIVE,
    "audit": ACCESS_FREE,
    "subscription": ACCESS_FREE,
}


MODULE_LABELS = {
    "dashboard": "dashboard",
    "clients": "clients",
    "services": "services",
    "expenses": "depenses",
    "products": "produits",
    "billing": "facturation",
    "accounting": "comptabilite",
    "apprenants": "apprenants",
    "users": "utilisateurs",
    "audit": "journal d'activites",
    "subscription": "abonnement",
}


def get_module_access_level(module_name):
    return MODULE_ACCESS_POLICY.get(module_name, ACCESS_FREE)


def get_module_label(module_name):
    return MODULE_LABELS.get(module_name, module_name)


def get_module_access_state(entreprise, module_name, *, as_of=None):
    level = get_module_access_level(module_name)
    if level == ACCESS_FREE:
        return {
            "allowed": True,
            "reason": None,
            "level": level,
            "subscription": get_current_subscription(entreprise),
        }

    subscription = refresh_subscription_status(entreprise, as_of=as_of)
    if subscription is None:
        return {
            "allowed": False,
            "reason": "missing_subscription",
            "level": level,
            "subscription": None,
        }

    if not subscription.actif:
        return {
            "allowed": False,
            "reason": "inactive_subscription",
            "level": level,
            "subscription": subscription,
        }

    if is_subscription_expired(subscription, as_of=as_of):
        return {
            "allowed": False,
            "reason": "expired_subscription",
            "level": level,
            "subscription": subscription,
        }

    if level == ACCESS_TRIAL_OR_ACTIVE and subscription.statut in {
        AbonnementEntreprise.Statut.ESSAI,
        AbonnementEntreprise.Statut.ACTIF,
    }:
        return {
            "allowed": True,
            "reason": None,
            "level": level,
            "subscription": subscription,
        }

    if level == ACCESS_ACTIVE_ONLY and subscription.statut == AbonnementEntreprise.Statut.ACTIF:
        return {
            "allowed": True,
            "reason": None,
            "level": level,
            "subscription": subscription,
        }

    reason = "active_subscription_required" if level == ACCESS_ACTIVE_ONLY else "subscription_not_eligible"
    return {
        "allowed": False,
        "reason": reason,
        "level": level,
        "subscription": subscription,
    }


def can_access_module(user, module_name, *, as_of=None):
    entreprise = get_user_entreprise_or_raise(user)
    return get_module_access_state(entreprise, module_name, as_of=as_of)["allowed"]


def get_module_access_denied_message(module_name, reason):
    module_label = get_module_label(module_name)
    if reason == "active_subscription_required":
        return f"Le module {module_label} est reserve aux entreprises avec un abonnement actif."
    if reason == "missing_subscription":
        return f"Le module {module_label} necessite un abonnement ou un essai actif."
    if reason in {"inactive_subscription", "expired_subscription"}:
        return f"L'acces au module {module_label} est indisponible car l'abonnement de votre entreprise n'est plus actif."
    return f"Vous ne pouvez pas acceder au module {module_label} avec l'etat actuel de votre abonnement."


def module_access_required(module_name):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            entreprise = get_user_entreprise_or_raise(request.user)
            state = get_module_access_state(entreprise, module_name)
            if not state["allowed"]:
                messages.error(request, get_module_access_denied_message(module_name, state["reason"]))
                expire_url = reverse("abonnement_expire")
                return redirect(f"{expire_url}?module={module_name}&reason={state['reason']}")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
