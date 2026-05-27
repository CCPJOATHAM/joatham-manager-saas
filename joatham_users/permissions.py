from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


ROLE_PROPRIETAIRE = "proprietaire"
ROLE_GESTIONNAIRE = "gestionnaire"
ROLE_COMPTABLE = "comptable"
ROLE_SUPER_ADMIN = "super_admin"


PERMISSIONS = {
    "superadmin.view": {ROLE_SUPER_ADMIN},
    "superadmin.manage": {ROLE_SUPER_ADMIN},
    "dashboard.owner": {ROLE_PROPRIETAIRE},
    "dashboard.management": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "dashboard.accounting": {ROLE_PROPRIETAIRE, ROLE_COMPTABLE},
    "clients.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "clients.manage": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "services.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "services.manage": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "billing.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "billing.manage": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "billing.payments": {ROLE_PROPRIETAIRE, ROLE_COMPTABLE},
    "payments.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "payments.create": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "payments.validate": {ROLE_PROPRIETAIRE, ROLE_COMPTABLE},
    "payments.cancel": {ROLE_PROPRIETAIRE},
    "payments.export": {ROLE_PROPRIETAIRE, ROLE_COMPTABLE},
    "expenses.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "expenses.manage": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "expenses.export": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "caisse.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "caisse.create": {ROLE_PROPRIETAIRE},
    "caisse.open_session": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "caisse.close_session": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "caisse.add_movement": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "caisse.validate_session": {ROLE_PROPRIETAIRE},
    "caisse.reject_session": {ROLE_PROPRIETAIRE},
    "caisse.export": {ROLE_PROPRIETAIRE, ROLE_COMPTABLE},
    "caisse.dashboard": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "caisse.manage_settings": {ROLE_PROPRIETAIRE},
    "products.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "products.manage": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "stock.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "stock.move": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "stock.adjust": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "stock.inventory": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "stock.export": {ROLE_PROPRIETAIRE, ROLE_COMPTABLE},
    "reports.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "reports.advanced_view": {ROLE_PROPRIETAIRE, ROLE_COMPTABLE},
    "reports.export": {ROLE_PROPRIETAIRE, ROLE_COMPTABLE},
    "accounting.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "accounting.export": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "apprenants.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "apprenants.add": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "apprenants.manage": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "apprenants.payments": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "rh.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "rh.manage": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "rh.presence": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "rh.documents": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "rh.reports": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE},
    "rh.link_user": {ROLE_PROPRIETAIRE},
    "subscription.view": {ROLE_PROPRIETAIRE},
    "company.manage": {ROLE_PROPRIETAIRE},
    "audit.view": {ROLE_PROPRIETAIRE, ROLE_COMPTABLE},
    "users.view": {ROLE_PROPRIETAIRE},
    "users.invite": {ROLE_PROPRIETAIRE},
    "users.change_role": {ROLE_PROPRIETAIRE},
    "users.activate": {ROLE_PROPRIETAIRE},
    "users.deactivate": {ROLE_PROPRIETAIRE},
    "users.remove": {ROLE_PROPRIETAIRE},
    "users.manage": {ROLE_PROPRIETAIRE},
    "messages.view": {ROLE_PROPRIETAIRE, ROLE_GESTIONNAIRE, ROLE_COMPTABLE},
    "suggestions.create": {ROLE_PROPRIETAIRE},
}


ROLE_HOME = {
    ROLE_SUPER_ADMIN: "super_admin_dashboard",
    ROLE_PROPRIETAIRE: "admin_dashboard",
    ROLE_GESTIONNAIRE: "gestion_dashboard",
    ROLE_COMPTABLE: "comptable_dashboard",
}


def get_user_role(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    normalized_role = getattr(user, "normalized_role", None)
    if normalized_role:
        return normalized_role
    return {"admin": ROLE_PROPRIETAIRE}.get(getattr(user, "role", None), getattr(user, "role", None))


def user_has_permission(user, permission_code):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    user_role = get_user_role(user)
    if user_role == ROLE_SUPER_ADMIN:
        return permission_code.startswith("superadmin.")

    allowed_roles = PERMISSIONS.get(permission_code)
    if allowed_roles is None:
        raise KeyError(f"Permission inconnue: {permission_code}")

    return user_role in allowed_roles


def require_permission(user, permission_code, message="Vous n'avez pas les droits pour cette action."):
    if not user_has_permission(user, permission_code):
        raise PermissionDenied(message)


def permission_required(permission_code, message="Vous n'avez pas les droits pour cette action."):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            require_permission(request.user, permission_code, message=message)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def get_default_dashboard_name(user):
    return ROLE_HOME.get(get_user_role(user), "login")
