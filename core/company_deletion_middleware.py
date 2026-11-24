from django.contrib.auth import logout
from django.http import HttpResponseForbidden
from django.utils.translation import gettext as _
from core.services.company_deletion import is_deletion_pending


class CompanyDeletionAccessMiddleware:
    """A pending request blocks every authenticated tenant route, including admin.

    Check the durable request independently of is_active, so a different legacy
    activation action cannot accidentally reopen a pending tenant.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        company_id = getattr(user, "entreprise_id", None)
        if user and user.is_authenticated and company_id and is_deletion_pending(company_id):
            logout(request)
            response = HttpResponseForbidden(_("Cette entreprise fait l'objet d'une demande de suppression. Contactez le super-administrateur."))
            response["Cache-Control"] = "no-store"
            return response
        return self.get_response(request)
