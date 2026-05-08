from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from core.services.subscription import get_current_subscription, is_free_plan, refresh_subscription_status
from core.services.tenancy import get_subscription_access_state, get_user_entreprise_or_raise

ACCESS_FREEMIUM = "freemium"
ACCESS_PREMIUM = "premium"
ACCESS_LOCKED = "locked"
ACCESS_FREE = ACCESS_FREEMIUM
ACCESS_TRIAL_OR_ACTIVE = ACCESS_FREEMIUM
ACCESS_ACTIVE_ONLY = ACCESS_PREMIUM


MODULE_ACCESS_POLICY = {
    "dashboard": ACCESS_FREEMIUM,
    "clients": ACCESS_FREEMIUM,
    "services": ACCESS_FREEMIUM,
    "expenses": ACCESS_FREEMIUM,
    "depenses": ACCESS_FREEMIUM,
    "products": ACCESS_FREEMIUM,
    "produits": ACCESS_FREEMIUM,
    "billing": ACCESS_FREEMIUM,
    "apprenants": ACCESS_FREEMIUM,
    "subscription": ACCESS_FREEMIUM,
    "accounting": ACCESS_PREMIUM,
    "audit": ACCESS_PREMIUM,
    "messages": ACCESS_PREMIUM,
    "users": ACCESS_PREMIUM,
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
    "messages": "messagerie",
    "subscription": "abonnement",
}

PLAN_MODULE_ALIASES = {
    "dashboard": "dashboard",
    "clients": "clients",
    "services": "services",
    "expenses": "depenses",
    "products": "produits",
    "billing": "factures",
    "accounting": "comptabilite",
    "apprenants": "apprenants",
    "users": "utilisateurs",
    "audit": "audit",
    "messages": "messages",
    "subscription": "abonnements",
}

PREMIUM_DENIED_REASONS = {"premium_required", "feature_not_declared", "module_not_in_plan"}


def get_module_access_level(module_name):
    return MODULE_ACCESS_POLICY.get(module_name, ACCESS_LOCKED)


def get_module_label(module_name):
    return MODULE_LABELS.get(module_name, module_name)


def get_module_access_state(entreprise, module_name, *, as_of=None):
    level = get_module_access_level(module_name)
    if level == ACCESS_LOCKED:
        return {
            "allowed": False,
            "reason": "feature_not_declared",
            "level": level,
            "subscription": get_current_subscription(entreprise),
            "locked": True,
        }

    refresh_subscription_status(entreprise, as_of=as_of)
    state = get_subscription_access_state(
        entreprise,
        as_of=as_of,
        allow_trial=(level == ACCESS_FREEMIUM),
    )
    if state["allowed"]:
        plan = getattr(state["subscription"], "plan", None)
        if level == ACCESS_PREMIUM and is_free_plan(plan):
            return {
                "allowed": False,
                "reason": "premium_required",
                "level": level,
                "subscription": state["subscription"],
                "locked": True,
            }

        plan_module = PLAN_MODULE_ALIASES.get(module_name, module_name)
        included_modules = set(getattr(plan, "modules_inclus", None) or [])
        accepted_plan_modules = {module_name, plan_module}
        if included_modules and included_modules.isdisjoint(accepted_plan_modules):
            return {
                "allowed": False,
                "reason": "module_not_in_plan",
                "level": level,
                "subscription": state["subscription"],
                "locked": True,
            }
        if module_name == "accounting" and plan is not None and not getattr(plan, "acces_comptabilite", True):
            return {
                "allowed": False,
                "reason": "module_not_in_plan",
                "level": level,
                "subscription": state["subscription"],
                "locked": True,
            }

    return {
        "allowed": state["allowed"],
        "reason": state["reason"],
        "level": level,
        "subscription": state["subscription"],
        "locked": state["reason"] in PREMIUM_DENIED_REASONS,
    }


def can_access_module(user, module_name, *, as_of=None):
    if getattr(user, "is_super_admin", False):
        return True
    entreprise = get_user_entreprise_or_raise(user)
    return get_module_access_state(entreprise, module_name, as_of=as_of)["allowed"]


def get_module_access_denied_message(module_name, reason):
    module_label = get_module_label(module_name)
    if reason in PREMIUM_DENIED_REASONS:
        return "Cette fonctionnalite est reservee aux plans premium."
    if reason == "active_subscription_required":
        return f"Le module {module_label} est reserve aux entreprises avec un abonnement actif."
    if reason == "missing_subscription":
        return f"Le module {module_label} necessite un plan actif."
    if reason in {"inactive_subscription", "expired_subscription"}:
        return f"L'acces au module {module_label} est indisponible car l'abonnement de votre entreprise n'est plus actif."
    if reason == "module_not_in_plan":
        return f"Le module {module_label} n'est pas inclus dans le plan actuel de votre entreprise."
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
