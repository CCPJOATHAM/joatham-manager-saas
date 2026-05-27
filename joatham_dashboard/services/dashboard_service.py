from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.services.currency import format_amount_for_entreprise, get_currency_code
from core.services.product_policy import PREMIUM_DENIED_REASONS, get_module_access_state
from core.services.subscription import get_current_subscription, refresh_subscription_status
from joatham_users.permissions import user_has_permission

from ..selectors.dashboard import get_dashboard_kpis_by_entreprise


def build_advanced_reports_quick_action(entreprise, user=None):
    if not user_has_permission(user, "reports.advanced_view"):
        return {"is_visible": False, "is_available": False, "url": "", "badge": ""}

    state = get_module_access_state(entreprise, "advanced_reports")
    if state.get("allowed"):
        return {"is_visible": True, "is_available": True, "url": reverse("advanced_reports"), "badge": ""}

    badge = _("Premium") if state.get("reason") in PREMIUM_DENIED_REASONS else _("Abonnement requis")
    return {"is_visible": True, "is_available": False, "url": "", "badge": badge}


def build_dashboard_context(entreprise, user=None):
    kpis = get_dashboard_kpis_by_entreprise(entreprise)
    subscription = refresh_subscription_status(entreprise) or get_current_subscription(entreprise)
    return {
        "currency_code": get_currency_code(entreprise),
        "advanced_reports_quick_action": build_advanced_reports_quick_action(entreprise, user),
        "total_ca": format_amount_for_entreprise(kpis["total_ca"], entreprise),
        "total_depenses": format_amount_for_entreprise(kpis["total_depenses"], entreprise),
        "benefice": format_amount_for_entreprise(kpis["benefice"], entreprise),
        "total_jour": format_amount_for_entreprise(kpis["total_jour"], entreprise),
        "total_mois": format_amount_for_entreprise(kpis["total_mois"], entreprise),
        "depense_jour": format_amount_for_entreprise(kpis["depense_jour"], entreprise),
        "depense_mois": format_amount_for_entreprise(kpis["depense_mois"], entreprise),
        "total_tva": format_amount_for_entreprise(kpis["total_tva"], entreprise),
        "total_encaisse": format_amount_for_entreprise(kpis["total_encaisse"], entreprise),
        "reste_encaisser": format_amount_for_entreprise(kpis["reste_encaisser"], entreprise),
        "payees": kpis["payees"],
        "impayees": kpis["impayees"],
        "nombre_factures": kpis["nombre_factures"],
        "nombre_clients": kpis["nombre_clients"],
        "nombre_apprenants": kpis["nombre_apprenants"],
        "labels": kpis["labels"],
        "data": kpis["data"],
        "recent_activity": kpis["recent_activity"],
        "flow_activity": kpis["flow_activity"],
        "rupture_products_count": kpis["rupture_products_count"],
        "low_stock_products_count": kpis["low_stock_products_count"],
        "rupture_products": kpis["rupture_products"],
        "low_stock_products": kpis["low_stock_products"],
        "subscription": subscription,
    }
