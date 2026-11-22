from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from core.company_deletion_forms import CompanyDeletionConfirmationForm
from core.models import CompanyDeletionRequest
from core.services.company_deletion import (
    DeletionWorkflowError, cancel_deletion, deletion_inventory, export_company, schedule_deletion,
)
from joatham_users.models import Entreprise
from joatham_users.permissions import permission_required
from django.conf import settings


@permission_required("superadmin.view", message=gettext_lazy("Action réservée au super-administrateur actif."))
@never_cache
@require_http_methods(["GET", "POST"])
def company_deletion_review(request, entreprise_id):
    company = get_object_or_404(Entreprise, pk=entreprise_id)
    form = CompanyDeletionConfirmationForm(request.POST if request.method == "POST" else None, expected_name=company.nom)
    if request.method == "POST" and form.is_valid():
        arguments = dict(company_id=company.pk, actor=request.user, **form.cleaned_data)
        try:
            action = request.POST.get("action")
            if action == "export":
                response = HttpResponse(export_company(**arguments), content_type="application/json; charset=utf-8")
                response["Content-Disposition"] = f'attachment; filename="entreprise-{company.pk}-structured.json"'
                response["X-Content-Type-Options"] = "nosniff"
                return response
            if action == "schedule":
                schedule_deletion(**arguments)
                messages.success(request, _("La suppression est programmée et l'accès est bloqué. Aucune donnée métier n'a été supprimée."))
            elif action == "cancel":
                cancel_deletion(**arguments)
                messages.success(request, _("La demande est annulée. L'état d'accès antérieur est restauré sans prolonger l'abonnement."))
            else:
                raise DeletionWorkflowError(_("Action non autorisée."))
            return redirect("super_admin_company_deletion", entreprise_id=company.pk)
        except DeletionWorkflowError as error:
            form.add_error(None, str(error))
    deletion = CompanyDeletionRequest.objects.filter(entreprise=company).first()
    try:
        inventory, inventory_error = deletion_inventory(company), ""
    except DeletionWorkflowError as error:
        inventory, inventory_error = [], str(error)
    return render(request, "core/company_deletion_review.html", {
        "entreprise": company, "form": form, "deletion": deletion,
        "is_pending": bool(deletion and deletion.status == "pending"),
        "window_expired": bool(deletion and deletion.status == "pending" and timezone.now() >= deletion.recovery_until),
        "inventory": inventory, "inventory_error": inventory_error,
        "grace_days": settings.JOATHAM_COMPANY_DELETION_GRACE_DAYS,
    })
