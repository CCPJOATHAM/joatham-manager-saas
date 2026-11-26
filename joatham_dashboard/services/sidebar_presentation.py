"""Presentation only: group the already-authorized navigation without filtering."""
from django.utils.translation import gettext_lazy as _


GROUPS = (
    ("workspace", _("Espace de travail"), {
        "dashboard": "dashboard", "message_conversation_list": "messages",
        "message_suggestion_create": "idea", "super_admin_dashboard": "dashboard",
        "super_admin_messages": "messages",
    }),
    ("sales", _("Ventes et services"), {
        "client_list": "people", "service_list": "work",
        "facture_list": "invoice", "proforma_list": "invoice",
    }),
    ("operations", _("Activités et équipes"), {
        "product_list": "stock", "apprenant_list": "people", "rh_employe_list": "people",
    }),
    ("finance", _("Finances et suivi"), {
        "depenses": "wallet", "caisse_list": "wallet", "payment_list": "wallet",
        "compta_dashboard": "bank", "advanced_reports": "chart",
    }),
    ("company", _("Organisation"), {
        "company_settings": "building", "user_list": "people",
        "activity_log_list": "chart", "subscription_overview": "wallet",
    }),
    ("platform", _("Administration SaaS"), {
        "super_admin_company_list": "building", "super_admin_user_list": "people",
        "super_admin_subscription_list": "wallet", "super_admin_settings": "settings",
        "super_admin_exchange_rate_list": "bank", "super_admin_audit_list": "chart",
    }),
)


def build_sidebar_groups(items):
    groups = []
    known = set()
    for key, label, icons in GROUPS:
        selected = [{**item, "icon": icons[item["key"]]} for item in items if item.get("key") in icons]
        if selected:
            groups.append({"key": key, "label": label, "items": selected})
            known.update(item["key"] for item in selected)
    remaining = [{**item, "icon": "dashboard"} for item in items if item.get("key") not in known]
    if remaining:
        groups.append({"key": "other", "label": _("Autres"), "items": remaining})
    return groups
