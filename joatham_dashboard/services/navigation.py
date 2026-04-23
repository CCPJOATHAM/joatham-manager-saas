from django.urls import reverse

from core.services.product_policy import can_access_module
from joatham_users.permissions import (
    get_default_dashboard_name,
    get_user_role,
    user_has_permission,
)


NAV_ITEMS = [
    {
        "label": "Super admin",
        "url_name": "super_admin_dashboard",
        "permission": "superadmin.view",
        "module": None,
        "roles": ["super_admin"],
        "prefixes": ["/super-admin/"],
    },
    {
        "label": "Dashboard",
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
        "label": "Entreprise",
        "url_name": "company_settings",
        "permission": "company.manage",
        "module": None,
        "prefixes": ["/entreprise/"],
    },
    {
        "label": "Clients",
        "url_name": "client_list",
        "permission": "clients.view",
        "module": "clients",
        "prefixes": ["/clients/"],
    },
    {
        "label": "Services",
        "url_name": "service_list",
        "permission": "services.view",
        "module": "services",
        "prefixes": ["/services/"],
    },
    {
        "label": "Depenses",
        "url_name": "depenses",
        "permission": "expenses.view",
        "module": "expenses",
        "prefixes": ["/depenses/"],
    },
    {
        "label": "Produits",
        "url_name": "product_list",
        "permission": "products.view",
        "module": "products",
        "prefixes": ["/produits/"],
    },
    {
        "label": "Factures",
        "url_name": "facture_list",
        "permission": "billing.view",
        "module": "billing",
        "prefixes": ["/factures/"],
    },
    {
        "label": "Comptabilite",
        "url_name": "compta_dashboard",
        "permission": "accounting.view",
        "module": "accounting",
        "prefixes": ["/compta/"],
    },
    {
        "label": "Apprenants",
        "url_name": "apprenant_list",
        "permission": "apprenants.view",
        "module": "apprenants",
        "prefixes": ["/apprenants/"],
    },
    {
        "label": "Utilisateurs",
        "url_name": "user_list",
        "permission": "users.manage",
        "module": "users",
        "prefixes": ["/utilisateurs/"],
    },
    {
        "label": "Audit",
        "url_name": "activity_log_list",
        "permission": "audit.view",
        "module": "audit",
        "roles": ["proprietaire"],
        "prefixes": ["/audit/"],
    },
    {
        "label": "Abonnement",
        "url_name": "subscription_overview",
        "permission": "subscription.view",
        "module": "subscription",
        "prefixes": ["/abonnement/"],
    },
]


ROLE_LABELS = {
    "super_admin": "Super admin",
    "proprietaire": "Proprietaire",
    "gestionnaire": "Gestionnaire",
    "comptable": "Comptable",
}


def _is_item_visible(user, item):
    roles = item.get("roles")
    if roles and get_user_role(user) not in roles:
        return False

    permission = item.get("permission")
    if permission and not user_has_permission(user, permission):
        return False

    module_name = item.get("module")
    if module_name:
        try:
            return can_access_module(user, module_name)
        except Exception:
            return False
    return True


def build_navigation_for_request(request):
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return []

    current_path = getattr(request, "path", "")
    items = []

    for item in NAV_ITEMS:
        if not _is_item_visible(user, item):
            continue

        url_name = item["url_name"] or get_default_dashboard_name(user)
        url = reverse(url_name)
        items.append(
            {
                "label": item["label"],
                "url": url,
                "is_active": any(current_path.startswith(prefix) for prefix in item["prefixes"]),
            }
        )

    return items


def get_role_label(user):
    return ROLE_LABELS.get(get_user_role(user), "")
