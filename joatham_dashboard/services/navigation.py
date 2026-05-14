from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.services.product_policy import PREMIUM_DENIED_REASONS, get_module_access_state
from core.services.tenancy import get_user_entreprise_or_raise
from joatham_users.permissions import (
    get_default_dashboard_name,
    get_user_role,
    user_has_permission,
)


NAV_ITEMS = [
    {
        "label": _("Pilotage SaaS"),
        "url_name": "super_admin_dashboard",
        "url": "/super-admin/",
        "permission": "superadmin.view",
        "module": None,
        "roles": ["super_admin"],
        "exact_paths": ["/super-admin/"],
    },
    {
        "label": _("Entreprises"),
        "url_name": "super_admin_company_list",
        "permission": "superadmin.view",
        "module": None,
        "roles": ["super_admin"],
        "prefixes": ["/super-admin/entreprises/"],
    },
    {
        "label": _("Utilisateurs"),
        "url_name": "super_admin_user_list",
        "permission": "superadmin.view",
        "module": None,
        "roles": ["super_admin"],
        "prefixes": ["/super-admin/utilisateurs/"],
    },
    {
        "label": _("Abonnements"),
        "url_name": "super_admin_subscription_list",
        "permission": "superadmin.view",
        "module": None,
        "roles": ["super_admin"],
        "prefixes": ["/super-admin/abonnements/"],
    },
    {
        "label": _("Audit / logs"),
        "url_name": "super_admin_audit_list",
        "permission": "superadmin.view",
        "module": None,
        "roles": ["super_admin"],
        "prefixes": ["/super-admin/audit/"],
    },
    {
        "label": _("Parametres plateforme"),
        "url_name": "super_admin_settings",
        "permission": "superadmin.view",
        "module": None,
        "roles": ["super_admin"],
        "prefixes": ["/super-admin/parametres/"],
    },
    {
        "label": _("Taux de change"),
        "url_name": "super_admin_exchange_rate_list",
        "permission": "superadmin.view",
        "module": None,
        "roles": ["super_admin"],
        "prefixes": ["/super-admin/taux-change/"],
    },
    {
        "label": _("Demandes SaaS"),
        "url_name": "super_admin_messages",
        "permission": "superadmin.view",
        "module": None,
        "roles": ["super_admin"],
        "prefixes": ["/super-admin/messages/"],
        "badge_counter": "super_admin_messages",
    },
    {
        "label": _("Dashboard"),
        "url_name": None,
        "permission": None,
        "module": "dashboard",
        "roles": ["proprietaire", "gestionnaire", "comptable"],
        "prefixes": [
            "/admin-dashboard/",
            "/proprietaire-dashboard/",
            "/gestion-dashboard/",
            "/comptable-dashboard/",
        ],
    },
    {
        "label": _("Messagerie"),
        "url_name": "message_conversation_list",
        "permission": "messages.view",
        "module": "messages",
        "roles": ["proprietaire", "gestionnaire", "comptable"],
        "exact_paths": ["/messages/"],
        "prefixes": ["/messages/nouvelle/", "/messages/conversation/", "/messages/piece-jointe/"],
        "badge_counter": "unread_messages",
    },
    {
        "label": _("Rapports avances"),
        "url_name": "advanced_reports",
        "permission": "reports.advanced_view",
        "module": "advanced_reports",
        "roles": ["proprietaire", "comptable"],
        "prefixes": ["/rapports-avances/"],
        "disabled_when_locked": True,
    },
    {
        "label": _("Organisation"),
        "url_name": "company_settings",
        "permission": "company.manage",
        "module": None,
        "prefixes": ["/entreprise/"],
    },
    {
        "label": _("Clients"),
        "url_name": "client_list",
        "permission": "clients.view",
        "module": "clients",
        "prefixes": ["/clients/"],
    },
    {
        "label": _("Services"),
        "url_name": "service_list",
        "permission": "services.view",
        "module": "services",
        "prefixes": ["/services/"],
    },
    {
        "label": _("Depenses"),
        "url_name": "depenses",
        "permission": "expenses.view",
        "module": "expenses",
        "prefixes": ["/depenses/"],
    },
    {
        "label": _("Caisse"),
        "url_name": "caisse_list",
        "permission": "caisse.view",
        "module": "caisse",
        "prefixes": ["/caisse/"],
    },
    {
        "label": _("Paiements"),
        "url_name": "payment_list",
        "permission": "payments.view",
        "module": "payments",
        "prefixes": ["/paiements/"],
        "disabled_when_locked": True,
    },
    {
        "label": _("Produits"),
        "url_name": "product_list",
        "permission": "products.view",
        "module": "products",
        "prefixes": ["/produits/"],
    },
    {
        "label": _("Factures"),
        "url_name": "facture_list",
        "permission": "billing.view",
        "module": "billing",
        "prefixes": ["/factures/"],
    },
    {
        "label": "Comptabilite",
        "translate_label": False,
        "url_name": "compta_dashboard",
        "permission": "accounting.view",
        "module": "accounting",
        "prefixes": ["/compta/"],
    },
    {
        "label": _("Apprenants"),
        "url_name": "apprenant_list",
        "permission": "apprenants.view",
        "module": "apprenants",
        "prefixes": ["/apprenants/"],
    },
    {
        "label": _("Utilisateurs"),
        "url_name": "user_list",
        "permission": "users.view",
        "module": "users",
        "roles": ["proprietaire"],
        "prefixes": ["/utilisateurs/"],
    },
    {
        "label": _("Audit"),
        "url_name": "activity_log_list",
        "permission": "audit.view",
        "module": "audit",
        "roles": ["proprietaire"],
        "prefixes": ["/audit/"],
    },
    {
        "label": _("Mon abonnement"),
        "url_name": "subscription_overview",
        "permission": "subscription.view",
        "module": "subscription",
        "prefixes": ["/abonnement/"],
    },
    {
        "label": _("Suggestions"),
        "url_name": "message_suggestion_create",
        "permission": "suggestions.create",
        "module": None,
        "roles": ["proprietaire"],
        "prefixes": ["/messages/suggestions/"],
    },
]


ROLE_LABELS = {
    "super_admin": _("Super admin"),
    "proprietaire": _("Proprietaire"),
    "gestionnaire": _("Gestionnaire"),
    "comptable": _("Comptable"),
}


def _get_module_state(user, module_name):
    entreprise = get_user_entreprise_or_raise(user)
    return get_module_access_state(entreprise, module_name)


def _get_item_state(user, item):
    roles = item.get("roles")
    if roles and get_user_role(user) not in roles:
        return {"visible": False}

    permission = item.get("permission")
    if permission and not user_has_permission(user, permission):
        return {"visible": False}

    module_name = item.get("module")
    if module_name:
        try:
            state = _get_module_state(user, module_name)
            if state.get("allowed"):
                return {"visible": True}
            if state.get("reason") in PREMIUM_DENIED_REASONS:
                return {
                    "visible": True,
                    "badge": _("Premium"),
                    "disabled": bool(item.get("disabled_when_locked")),
                }
            if state.get("reason") == "active_subscription_required":
                return {
                    "visible": True,
                    "badge": _("Abonnement requis"),
                }
            return {"visible": False}
        except Exception:
            if module_name == "accounting":
                try:
                    state = _get_module_state(user, module_name)
                except Exception:
                    return {"visible": False}
                if not state.get("allowed"):
                    return {
                        "visible": True,
                        "badge": _("Abonnement requis"),
                    }
            return {"visible": False}
    return {"visible": True}


def build_navigation_for_request(request):
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return []

    current_path = getattr(request, "path", "")
    items = []

    for item in NAV_ITEMS:
        item_state = _get_item_state(user, item)
        if not item_state.get("visible"):
            continue

        is_disabled = bool(item.get("disabled") or item_state.get("disabled"))
        url = ""
        if not is_disabled:
            if item.get("url"):
                url = item["url"]
            else:
                url_name = item["url_name"] or get_default_dashboard_name(user)
                url = reverse(url_name)
            if item.get("url_fragment"):
                url = f"{url}#{item['url_fragment']}"
        exact_paths = item.get("exact_paths", [])
        prefixes = item.get("prefixes", [])
        badge_count = _get_badge_count(user, item.get("badge_counter"))
        items.append(
            {
                "label": item["label"],
                "url": url,
                "is_active": not is_disabled and (current_path in exact_paths or any(current_path.startswith(prefix) for prefix in prefixes)),
                "badge": item_state.get("badge") or item.get("badge"),
                "badge_count": badge_count,
                "is_disabled": is_disabled,
                "translate_label": item.get("translate_label", True),
            }
        )

    return items


def _get_badge_count(user, counter_name):
    if not counter_name:
        return 0
    try:
        if counter_name == "unread_messages":
            from joatham_messages.selectors.messages import get_unread_message_count

            return get_unread_message_count(user)
        if counter_name == "super_admin_messages":
            from joatham_messages.selectors.messages import get_pending_super_admin_message_count

            return get_pending_super_admin_message_count()
    except Exception:
        return 0
    return 0


def get_role_label(user):
    return ROLE_LABELS.get(get_user_role(user), "")
