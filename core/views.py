from django.utils.dateparse import parse_date
from django.contrib import messages
from django.shortcuts import redirect, render

from core.audit import record_audit_event
from core.forms import EntrepriseSettingsForm, PaiementAbonnementForm
from core.services.subscription import (
    calculate_subscription_payment_amount,
    create_subscription_payment_request,
    get_current_subscription,
    get_subscription_payment_duration_options,
    refresh_subscription_status,
    refuse_subscription_payment,
    validate_subscription_payment,
)
from core.services.super_admin import (
    activate_company_subscription,
    change_company_plan,
    extend_company_trial,
    get_entreprise_for_super_admin,
    get_plan_for_super_admin,
    refresh_all_subscription_statuses,
    suspend_company_subscription,
)
from core.services.tenancy import get_user_entreprise_or_raise
from core.ui_text import FLASH_MESSAGES
from core.services.world import build_country_currency_map
from joatham_users.models import Abonnement, AbonnementEntreprise
from joatham_users.permissions import permission_required

from .selectors.audit import (
    get_activity_actions_for_entreprise,
    get_activity_logs_by_entreprise,
    get_activity_modules_for_entreprise,
    get_activity_roles_for_entreprise,
    get_activity_users_for_entreprise,
)
from .selectors.super_admin import (
    get_super_admin_entreprise_queryset,
    get_super_admin_subscription_counts,
)
from .selectors.subscription_payments import (
    get_pending_subscription_payments,
    get_subscription_payment_for_super_admin,
    get_subscription_payments_by_entreprise,
)


@permission_required("audit.view")
def activity_log_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    selected_module = request.GET.get("module", "").strip()
    selected_user = request.GET.get("utilisateur", "").strip()
    selected_action = request.GET.get("action", "").strip()
    selected_role = request.GET.get("role", "").strip()
    selected_date_from = request.GET.get("date_from", "").strip()
    selected_date_to = request.GET.get("date_to", "").strip()

    logs = get_activity_logs_by_entreprise(
        entreprise,
        module=selected_module or None,
        utilisateur_id=selected_user or None,
        action=selected_action or None,
        role=selected_role or None,
        date_from=parse_date(selected_date_from) if selected_date_from else None,
        date_to=parse_date(selected_date_to) if selected_date_to else None,
    )

    context = {
        "logs": logs,
        "log_count": logs.count(),
        "modules": get_activity_modules_for_entreprise(entreprise),
        "users": get_activity_users_for_entreprise(entreprise),
        "actions": get_activity_actions_for_entreprise(entreprise),
        "roles": get_activity_roles_for_entreprise(entreprise),
        "selected_module": selected_module,
        "selected_user": selected_user,
        "selected_action": selected_action,
        "selected_role": selected_role,
        "selected_date_from": selected_date_from,
        "selected_date_to": selected_date_to,
        "entreprise": entreprise,
    }
    return render(request, "core/activity_log_list.html", context)


@permission_required("subscription.view")
def subscription_overview(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    subscription = refresh_subscription_status(entreprise)
    context = {
        "entreprise": entreprise,
        "subscription": subscription or get_current_subscription(entreprise),
        "paiements": get_subscription_payments_by_entreprise(entreprise)[:8],
    }
    return render(request, "core/subscription_overview.html", context)


@permission_required("subscription.view")
def subscription_payment_create(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = PaiementAbonnementForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        paiement = create_subscription_payment_request(
            entreprise=entreprise,
            plan=form.cleaned_data["plan"],
            duree=form.cleaned_data["duree"],
            reference_paiement=form.cleaned_data["reference_paiement"],
            preuve_paiement=form.cleaned_data.get("preuve_paiement"),
            utilisateur=request.user,
        )
        messages.success(request, "Votre demande de paiement a ete envoyee. Elle sera activee apres validation.")
        return redirect("subscription_overview")

    plans = Abonnement.objects.filter(actif=True).order_by("prix", "nom")
    duration_options = get_subscription_payment_duration_options()
    pricing_matrix = {
        f"{plan.id}:{duree}": str(calculate_subscription_payment_amount(plan=plan, duree=duree))
        for plan in plans
        for duree in duration_options
    }
    context = {
        "entreprise": entreprise,
        "form": form,
        "plans": plans,
        "duration_options": duration_options,
        "pricing_matrix": pricing_matrix,
    }
    return render(request, "core/subscription_payment_form.html", context)


@permission_required("company.manage")
def company_settings(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    form = EntrepriseSettingsForm(request.POST or None, request.FILES or None, instance=entreprise)

    if request.method == "POST" and form.is_valid():
        entreprise = form.save()
        record_audit_event(
            entreprise=entreprise,
            utilisateur=request.user,
            action="entreprise_modifiee",
            module="company",
            objet_type="Entreprise",
            objet_id=entreprise.id,
            description=f"Parametres de l'entreprise mis a jour pour {entreprise.nom}.",
            metadata={
                "logo": bool(entreprise.logo),
                "devise": entreprise.devise,
                "taux_tva_defaut": str(entreprise.taux_tva_defaut),
                "referentiel_comptable": entreprise.referentiel_comptable,
            },
        )
        messages.success(request, FLASH_MESSAGES["company_updated"])
        return redirect("company_settings")

    return render(
        request,
        "core/company_settings.html",
        {
            "entreprise": entreprise,
            "form": form,
            "country_currency_map": build_country_currency_map(),
        },
    )


@permission_required("superadmin.view")
def super_admin_dashboard(request):
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        try:
            if action == "validate_payment":
                paiement = get_subscription_payment_for_super_admin(request.POST.get("paiement_id"))
                validate_subscription_payment(paiement=paiement, super_admin=request.user)
                messages.success(request, f"Paiement valide pour {paiement.entreprise.nom}.")
                return redirect("super_admin_dashboard")
            if action == "refuse_payment":
                paiement = get_subscription_payment_for_super_admin(request.POST.get("paiement_id"))
                refuse_subscription_payment(paiement=paiement, super_admin=request.user)
                messages.success(request, f"Paiement refuse pour {paiement.entreprise.nom}.")
                return redirect("super_admin_dashboard")

            entreprise = get_entreprise_for_super_admin(request.POST.get("entreprise_id"))
            selected_plan_id = request.POST.get("plan_id")
            plan = get_plan_for_super_admin(selected_plan_id) if selected_plan_id else None

            if action == "activate":
                if plan is None:
                    raise ValueError("Veuillez selectionner un plan pour activer l'abonnement.")
                activate_company_subscription(entreprise=entreprise, plan=plan, utilisateur=request.user)
                messages.success(request, f"Abonnement active pour {entreprise.nom}.")
            elif action == "suspend":
                suspend_company_subscription(entreprise=entreprise, utilisateur=request.user)
                messages.success(request, f"Entreprise suspendue : {entreprise.nom}.")
            elif action == "extend_trial":
                extend_company_trial(
                    entreprise=entreprise,
                    days=request.POST.get("trial_days") or 7,
                    utilisateur=request.user,
                    plan=plan,
                )
                messages.success(request, f"Essai prolonge pour {entreprise.nom}.")
            elif action == "change_plan":
                if plan is None:
                    raise ValueError("Veuillez selectionner un plan pour modifier l'abonnement.")
                change_company_plan(entreprise=entreprise, plan=plan, utilisateur=request.user)
                messages.success(request, f"Plan mis a jour pour {entreprise.nom}.")
            else:
                messages.error(request, "Action super admin inconnue.")
        except ValueError as exc:
            messages.error(request, str(exc))

        return redirect("super_admin_dashboard")

    refresh_all_subscription_statuses(utilisateur=request.user)
    search = (request.GET.get("q") or "").strip()
    selected_statut = (request.GET.get("statut") or "").strip()
    context = {
        "counts": get_super_admin_subscription_counts(),
        "entreprises": get_super_admin_entreprise_queryset(search=search or None, statut=selected_statut or None),
        "plans": Abonnement.objects.filter(actif=True).order_by("prix", "nom"),
        "selected_search": search,
        "selected_statut": selected_statut,
        "statut_choices": AbonnementEntreprise.Statut.choices,
        "pending_payments": get_pending_subscription_payments(),
    }
    return render(request, "core/super_admin_dashboard.html", context)
