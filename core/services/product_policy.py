from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from core.services.subscription import (
    PREMIUM_PLAN_CODE,
    get_current_subscription,
    is_free_plan,
    normalize_plan_code,
    refresh_subscription_status,
)
from core.services.tenancy import get_subscription_access_state, get_user_entreprise_or_raise

ACCESS_INCLUDED_PLAN = "included_plan"
ACCESS_PREMIUM = "premium"
ACCESS_LOCKED = "locked"
ACCESS_FREE = ACCESS_INCLUDED_PLAN
ACCESS_FREEMIUM = ACCESS_INCLUDED_PLAN
ACCESS_TRIAL_OR_ACTIVE = ACCESS_INCLUDED_PLAN
ACCESS_ACTIVE_ONLY = ACCESS_PREMIUM


MODULE_ACCESS_POLICY = {
    "dashboard": ACCESS_INCLUDED_PLAN,
    "clients": ACCESS_INCLUDED_PLAN,
    "services": ACCESS_INCLUDED_PLAN,
    "expenses": ACCESS_INCLUDED_PLAN,
    "depenses": ACCESS_INCLUDED_PLAN,
    "caisse": ACCESS_INCLUDED_PLAN,
    "caisse_reports": ACCESS_INCLUDED_PLAN,
    "caisse_exports": ACCESS_INCLUDED_PLAN,
    "caisse_integrations": ACCESS_INCLUDED_PLAN,
    "caisse_validation": ACCESS_INCLUDED_PLAN,
    "products": ACCESS_INCLUDED_PLAN,
    "produits": ACCESS_INCLUDED_PLAN,
    "stock": ACCESS_INCLUDED_PLAN,
    "stock_reports": ACCESS_INCLUDED_PLAN,
    "stock_exports": ACCESS_INCLUDED_PLAN,
    "inventory": ACCESS_INCLUDED_PLAN,
    "billing": ACCESS_INCLUDED_PLAN,
    "payments": ACCESS_PREMIUM,
    "mobile_money": ACCESS_PREMIUM,
    "payment_validation": ACCESS_PREMIUM,
    "payments_reports": ACCESS_PREMIUM,
    "payments_exports": ACCESS_PREMIUM,
    "apprenants": ACCESS_INCLUDED_PLAN,
    "subscription": ACCESS_INCLUDED_PLAN,
    "accounting": ACCESS_PREMIUM,
    "accounting_reports": ACCESS_PREMIUM,
    "accounting_exports": ACCESS_PREMIUM,
    "advanced_reports": ACCESS_PREMIUM,
    "advanced_reports_exports": ACCESS_PREMIUM,
    "business_dashboard": ACCESS_PREMIUM,
    "audit": ACCESS_PREMIUM,
    "audit_advanced": ACCESS_PREMIUM,
    "messages": ACCESS_PREMIUM,
    "users": ACCESS_INCLUDED_PLAN,
    "rh": ACCESS_PREMIUM,
}


MODULE_LABELS = {
    "dashboard": "dashboard",
    "clients": "clients",
    "services": "services",
    "expenses": "depenses",
    "caisse": "caisse",
    "caisse_reports": "rapports caisse",
    "caisse_exports": "exports caisse",
    "caisse_integrations": "liaison caisse",
    "caisse_validation": "validation caisse",
    "products": "produits",
    "stock": "stock avance",
    "stock_reports": "rapports stock",
    "stock_exports": "exports stock",
    "inventory": "inventaire physique",
    "billing": "facturation",
    "payments": "paiements",
    "mobile_money": "Mobile Money",
    "payment_validation": "validation paiements",
    "payments_reports": "rapports paiements",
    "payments_exports": "exports paiements",
    "accounting": "comptabilite",
    "accounting_reports": "rapports financiers",
    "accounting_exports": "exports comptables",
    "advanced_reports": "rapports avances",
    "advanced_reports_exports": "exports rapports avances",
    "business_dashboard": "tableau de bord decisionnel",
    "apprenants": "apprenants",
    "users": "utilisateurs",
    "audit": "journal d'activites",
    "audit_advanced": "audit avance",
    "messages": "messagerie",
    "subscription": "abonnement",
    "rh": "ressources humaines",
}

PLAN_MODULE_ALIASES = {
    "dashboard": {"dashboard"},
    "clients": {"clients"},
    "services": {"services"},
    "expenses": {"expenses", "depenses"},
    "depenses": {"expenses", "depenses"},
    "caisse": {"caisse"},
    "caisse_reports": {"caisse_reports", "rapports_caisse"},
    "caisse_exports": {"caisse_exports", "exports_caisse", "exports"},
    "caisse_integrations": {"caisse_integrations", "liaison_caisse"},
    "caisse_validation": {"caisse_validation", "validation_caisse"},
    "products": {"products", "produits"},
    "produits": {"products", "produits"},
    "stock": {"stock", "stock_avance"},
    "stock_reports": {"stock_reports", "rapports_stock"},
    "stock_exports": {"stock_exports", "exports_stock", "exports"},
    "inventory": {"inventory", "inventaire"},
    "billing": {"billing", "factures"},
    "payments": {"payments", "paiements"},
    "mobile_money": {"mobile_money", "mobile-money", "mobilemoney"},
    "payment_validation": {"payment_validation", "validation_paiements"},
    "payments_reports": {"payments_reports", "rapports_paiements"},
    "payments_exports": {"payments_exports", "exports_paiements", "exports"},
    "accounting": {"accounting", "comptabilite"},
    "accounting_reports": {"accounting_reports", "rapports_financiers"},
    "accounting_exports": {"accounting_exports", "exports_comptables", "exports"},
    "advanced_reports": {"advanced_reports", "rapports_avances"},
    "advanced_reports_exports": {"advanced_reports_exports", "exports_rapports_avances", "exports"},
    "business_dashboard": {"business_dashboard", "tableau_bord_decisionnel"},
    "apprenants": {"apprenants"},
    "users": {"users", "utilisateurs"},
    "audit": {"audit"},
    "audit_advanced": {"audit_advanced", "audit_avance"},
    "messages": {"messages"},
    "subscription": {"subscription", "abonnements"},
    "rh": {"rh", "hr", "ressources_humaines", "human_resources"},
}

_MODULE_ALIAS_OWNERS = {}
_AMBIGUOUS_MODULE_ALIASES = set()
for canonical_module, aliases in PLAN_MODULE_ALIASES.items():
    for alias in {canonical_module, *aliases}:
        existing_owner = _MODULE_ALIAS_OWNERS.get(alias)
        if existing_owner and existing_owner != canonical_module:
            _AMBIGUOUS_MODULE_ALIASES.add(alias)
        else:
            _MODULE_ALIAS_OWNERS[alias] = canonical_module

MODULE_CANONICAL_NAMES = {
    alias: canonical_module
    for alias, canonical_module in _MODULE_ALIAS_OWNERS.items()
    if alias not in _AMBIGUOUS_MODULE_ALIASES
}

EXPORT_MODULES = {"stock_exports", "caisse_exports", "accounting_exports", "payments_exports", "advanced_reports_exports"}
ACCOUNTING_MODULES = {"accounting", "accounting_reports", "accounting_exports"}
PAYMENTS_PREMIUM_MODULES = {"payments", "mobile_money", "payment_validation", "payments_reports", "payments_exports"}
ADVANCED_REPORTS_PREMIUM_MODULES = {"advanced_reports", "advanced_reports_exports", "business_dashboard"}
RH_PREMIUM_MODULES = {"rh"}
PREMIUM_CODE_ONLY_MODULES = PAYMENTS_PREMIUM_MODULES | ADVANCED_REPORTS_PREMIUM_MODULES | RH_PREMIUM_MODULES
PREMIUM_DENIED_REASONS = {
    "premium_required",
    "feature_not_declared",
    "module_not_in_plan",
    "exports_not_in_plan",
    "accounting_not_in_plan",
}


def get_canonical_module_name(module_name):
    return MODULE_CANONICAL_NAMES.get(module_name, module_name)


def get_module_access_level(module_name):
    return MODULE_ACCESS_POLICY.get(get_canonical_module_name(module_name), ACCESS_LOCKED)


def get_module_label(module_name):
    canonical_module = get_canonical_module_name(module_name)
    return MODULE_LABELS.get(module_name) or MODULE_LABELS.get(canonical_module, module_name)


def get_plan_module_aliases(module_name):
    canonical_module = get_canonical_module_name(module_name)
    return (
        set(PLAN_MODULE_ALIASES.get(canonical_module, {canonical_module}))
        | set(PLAN_MODULE_ALIASES.get(module_name, set()))
        | {canonical_module, module_name}
    )


def is_module_explicitly_missing_from_plan(plan, module_name):
    included_modules = set(getattr(plan, "modules_inclus", None) or [])
    if not included_modules:
        return False
    accepted_plan_modules = get_plan_module_aliases(module_name)
    return included_modules.isdisjoint(accepted_plan_modules)


def get_module_access_state(entreprise, module_name, *, as_of=None):
    canonical_module = get_canonical_module_name(module_name)
    level = get_module_access_level(canonical_module)
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
        allow_trial=(level == ACCESS_INCLUDED_PLAN),
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
        if canonical_module in PREMIUM_CODE_ONLY_MODULES:
            if normalize_plan_code(plan) != PREMIUM_PLAN_CODE:
                return {
                    "allowed": False,
                    "reason": "premium_required",
                    "level": level,
                    "subscription": state["subscription"],
                    "locked": True,
                }
            if is_module_explicitly_missing_from_plan(plan, canonical_module):
                return {
                    "allowed": False,
                    "reason": "module_not_in_plan",
                    "level": level,
                    "subscription": state["subscription"],
                    "locked": True,
                }
            return {
                "allowed": True,
                "reason": None,
                "level": level,
                "subscription": state["subscription"],
                "locked": False,
            }

        if is_module_explicitly_missing_from_plan(plan, canonical_module):
            return {
                "allowed": False,
                "reason": "module_not_in_plan",
                "level": level,
                "subscription": state["subscription"],
                "locked": True,
            }
        if canonical_module in ACCOUNTING_MODULES and plan is not None and not getattr(plan, "acces_comptabilite", True):
            return {
                "allowed": False,
                "reason": "accounting_not_in_plan",
                "level": level,
                "subscription": state["subscription"],
                "locked": True,
            }
        if canonical_module in EXPORT_MODULES and plan is not None and not getattr(plan, "acces_exports", True):
            return {
                "allowed": False,
                "reason": "exports_not_in_plan",
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
    if reason == "module_not_in_plan":
        return f"Le module {module_label} n'est pas inclus dans le plan actuel de votre entreprise."
    if reason == "exports_not_in_plan":
        return "Les exports avances ne sont pas inclus dans le plan actuel de votre entreprise."
    if reason == "accounting_not_in_plan":
        return "La comptabilite avancee n'est pas incluse dans le plan actuel de votre entreprise."
    if reason == "premium_required":
        return "Cette fonctionnalite est reservee aux plans superieurs."
    if reason == "feature_not_declared":
        return "Cette fonctionnalite n'est pas disponible dans l'offre actuelle."
    if reason == "active_subscription_required":
        return f"Le module {module_label} necessite un plan actif compatible."
    if reason == "missing_subscription":
        return f"Le module {module_label} necessite un plan actif."
    if reason in {"inactive_subscription", "expired_subscription"}:
        return f"L'acces au module {module_label} est indisponible car le plan actuel de votre entreprise n'est plus actif."
    return f"Vous ne pouvez pas acceder au module {module_label} avec votre plan actuel."


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
