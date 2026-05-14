from django.db import OperationalError, ProgrammingError
from django.shortcuts import render
from django.utils import translation
from django.utils.translation import gettext_lazy as _

from core.models import PlatformSettings
from core.services.language import get_request_language, resolve_language_code


MODULE_LABELS = {
    "dashboard": _("Dashboard"),
    "clients": _("Clients"),
    "factures": _("Factures"),
    "services": _("Services"),
    "depenses": _("Depenses"),
    "comptabilite": _("Comptabilite"),
    "apprenants": _("Apprenants"),
    "abonnements": _("Abonnements"),
    "rapports": _("Rapports avances"),
    "utilisateurs": _("Utilisateurs"),
    "messages": _("Messagerie"),
}

MODULE_PREFIXES = [
    ("dashboard", ("/admin-dashboard/", "/proprietaire-dashboard/", "/gestion-dashboard/", "/comptable-dashboard/")),
    ("clients", ("/clients/",)),
    ("factures", ("/factures/",)),
    ("services", ("/services/",)),
    ("depenses", ("/depenses/",)),
    ("comptabilite", ("/compta/",)),
    ("apprenants", ("/apprenants/",)),
    ("abonnements", ("/abonnement/",)),
    ("rapports", ("/rapports-avances/",)),
    ("utilisateurs", ("/utilisateurs/",)),
    ("messages", ("/messages/",)),
]

MAINTENANCE_EXEMPT_PREFIXES = (
    "/i18n/",
    "/login/",
    "/logout/",
    "/health/",
    "/super-admin/",
    "/static/",
    "/media/",
)


def _get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _parse_allowed_ips(raw_value):
    normalized = (raw_value or "").replace(",", "\n")
    return {item.strip() for item in normalized.splitlines() if item.strip()}


def _is_super_admin_user(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    role = getattr(user, "normalized_role", None) or getattr(user, "role", None)
    return role == "super_admin" or bool(getattr(user, "is_superuser", False))


def _is_exempt_path(path):
    return any(path.startswith(prefix) for prefix in MAINTENANCE_EXEMPT_PREFIXES)


def _get_request_module(path):
    for module, prefixes in MODULE_PREFIXES:
        if any(path.startswith(prefix) for prefix in prefixes):
            return module
    return None


class PlatformMaintenanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""
        if _is_exempt_path(path):
            return self.get_response(request)

        try:
            platform_settings = PlatformSettings.get_solo()
        except (OperationalError, ProgrammingError):
            return self.get_response(request)

        user = getattr(request, "user", None)
        client_ip = _get_client_ip(request)
        allowed_ip = bool(client_ip and client_ip in _parse_allowed_ips(platform_settings.maintenance_allowed_ips))

        if platform_settings.mode_maintenance:
            if _is_super_admin_user(user) or allowed_ip:
                return self.get_response(request)

            return render(
                request,
                "core/maintenance.html",
                {
                    "platform_name": platform_settings.nom_plateforme,
                    "message": platform_settings.message_maintenance,
                },
                status=503,
            )

        module = _get_request_module(path)
        if not module or module not in (platform_settings.maintenance_modules or []):
            return self.get_response(request)

        if _is_super_admin_user(user) or allowed_ip:
            return self.get_response(request)

        module_label = MODULE_LABELS.get(module, module)
        return render(
            request,
            "core/maintenance.html",
            {
                "platform_name": platform_settings.nom_plateforme,
                "message": _("Le module %(module)s est momentanement en maintenance.") % {"module": module_label},
                "module_label": module_label,
            },
            status=503,
        )


class UserLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        language_code = get_request_language(request)
        translation.activate(language_code)
        request.LANGUAGE_CODE = language_code

        response = self.get_response(request)
        response_language = resolve_language_code(getattr(request, "LANGUAGE_CODE", language_code)) or language_code
        response.setdefault("Content-Language", response_language)
        return response
