from django.urls import reverse

from core.services.currency import format_amount_for_entreprise, get_currency_code
from core.services.subscription import get_current_subscription, refresh_subscription_status

from ..selectors.dashboard import get_dashboard_kpis_by_entreprise
from .navigation import NAV_ITEMS, _get_item_state


def build_advanced_reports_quick_action(entreprise, user=None):
    reports_item = next((item for item in NAV_ITEMS if item.get("url_name") == "advanced_reports"), None)
    if not reports_item:
        return {"is_visible": False, "is_available": False, "url": "", "badge": ""}

    item_state = _get_item_state(user, reports_item)
    if not item_state.get("visible"):
        return {"is_visible": False, "is_available": False, "url": "", "badge": ""}

    is_disabled = bool(reports_item.get("disabled") or item_state.get("disabled"))
    return {
        "is_visible": True,
        "is_available": not is_disabled,
        "url": "" if is_disabled else reverse("advanced_reports"),
        "badge": item_state.get("badge") or reports_item.get("badge") or "",
    }


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
