from core.services.company_profile import build_entreprise_identity
from core.services.tenancy import get_user_entreprise
from joatham_dashboard.services.navigation import build_navigation_for_request, get_role_label
from joatham_dashboard.services.sidebar_presentation import build_sidebar_groups


def entreprise_identity(request):
    user = getattr(request, "user", None)
    entreprise = get_user_entreprise(user)
    navigation = build_navigation_for_request(request)
    return {
        "entreprise_identity": build_entreprise_identity(entreprise) if entreprise else {},
        "dashboard_navigation": navigation,
        "sidebar_groups": build_sidebar_groups(navigation),
        "user_role_label": get_role_label(user),
        "user_role_key": getattr(user, "normalized_role", ""),
    }
