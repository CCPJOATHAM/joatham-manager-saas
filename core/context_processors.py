from core.services.company_profile import build_entreprise_identity
from core.services.tenancy import get_user_entreprise
from joatham_dashboard.services.navigation import build_navigation_for_request, get_role_label


def entreprise_identity(request):
    entreprise = get_user_entreprise(getattr(request, "user", None))
    return {
        "entreprise_identity": build_entreprise_identity(entreprise) if entreprise else {},
        "dashboard_navigation": build_navigation_for_request(request),
        "user_role_label": get_role_label(getattr(request, "user", None)),
    }
