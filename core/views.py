from django.utils.dateparse import parse_date
from django.utils import timezone
from django.contrib import messages
from django.db import models
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from urllib.parse import quote

from core.audit import record_audit_event
from core.forms import EntrepriseSettingsForm, ExchangeRateManualForm, ManualSubscriptionPaymentForm, PaiementAbonnementForm, PlatformSettingsForm
from core.models import ActivityLog, ExchangeRate, PaiementAbonnement, PlatformSettings
from core.services.subscription import (
    DEFAULT_WHATSAPP_MESSAGE,
    DEFAULT_WHATSAPP_NUMBER,
    build_subscription_payment_estimate,
    build_subscription_pricing_matrix,
    create_subscription_plan_request,
    create_subscription_payment_request,
    get_commercial_plans_queryset,
    get_current_subscription,
    get_plan_feature_summary,
    get_plan_quota_profile,
    get_pending_subscription_plan_request,
    get_subscription_payment_duration_options,
    is_free_plan,
    normalize_plan_code,
    register_manual_subscription_payment,
    refuse_subscription_plan_request,
    refresh_subscription_status,
    refuse_subscription_payment,
    validate_subscription_payment,
    validate_subscription_plan_request,
)
from core.services.currency import get_currency_code
from core.services.exchange_rates import ExchangeRateUnavailable, get_exchange_rate, get_plan_price_for_company
from core.services.product_policy import module_access_required
from core.services.super_admin import (
    activate_company_subscription,
    deactivate_company_for_super_admin,
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
from joatham_users.models import AbonnementEntreprise, Entreprise, User
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


def _safe_related_count(instance, related_name):
    manager = getattr(instance, related_name, None)
    if manager is None:
        return 0
    return manager.count()


def _handle_super_admin_subscription_action(request, *, redirect_name):
    action = (request.POST.get("action") or "").strip()
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
        messages.success(request, f"Acces historique prolonge pour {entreprise.nom}.")
    elif action == "change_plan":
        if plan is None:
            raise ValueError("Veuillez selectionner un plan pour modifier l'abonnement.")
        change_company_plan(entreprise=entreprise, plan=plan, utilisateur=request.user)
        messages.success(request, f"Plan mis a jour pour {entreprise.nom}.")
    else:
        messages.error(request, "Action super admin inconnue.")

    return redirect(redirect_name)


def _record_super_admin_user_action(*, target_user, admin_user, action):
    entreprise = getattr(target_user, "entreprise", None)
    if entreprise is None:
        return None
    return record_audit_event(
        entreprise=entreprise,
        utilisateur=admin_user,
        action=action,
        module="super_admin",
        objet_type="User",
        objet_id=target_user.id,
        description=f"Compte utilisateur {target_user.username} {action.replace('_', ' ')} par super admin.",
        metadata={
            "target_user_id": target_user.id,
            "target_username": target_user.username,
            "target_email": target_user.email,
            "target_role": target_user.normalized_role,
        },
    )


@permission_required("audit.view")
@module_access_required("audit")
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
    plans = get_commercial_plans_queryset(include_free=False, paid_only=True).order_by("prix", "nom")
    for plan in plans:
        plan.company_price = get_plan_price_for_company(plan, entreprise)
    pricing_options = []
    featured_plan = plans.first()
    if featured_plan is not None:
        for duree, details in get_subscription_payment_duration_options().items():
            estimate = build_subscription_payment_estimate(entreprise=entreprise, plan=featured_plan, duree=duree)
            pricing_options.append(
                {
                    "code": duree,
                    "label": details["label"],
                    "amount_usd": estimate["amount_usd"],
                    "currency_code": estimate["currency_code"],
                    "estimated_amount": estimate["estimated_amount"],
                    "exchange_rate": estimate["exchange_rate"],
                }
            )
    context = {
        "entreprise": entreprise,
        "currency_code": get_currency_code(entreprise),
        "subscription": subscription or get_current_subscription(entreprise),
        "is_current_free_plan": bool(subscription and is_free_plan(subscription.plan)),
        "current_plan_features": get_plan_feature_summary(subscription.plan) if subscription else [],
        "current_plan_quota_profile": get_plan_quota_profile(subscription.plan) if subscription else {},
        "paiements": get_subscription_payments_by_entreprise(entreprise)[:8],
        "featured_plan": featured_plan,
        "pricing_options": pricing_options,
        "whatsapp_link": f"https://wa.me/{DEFAULT_WHATSAPP_NUMBER}?text={quote(DEFAULT_WHATSAPP_MESSAGE)}",
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
            telephone_paiement=form.cleaned_data.get("telephone_paiement", ""),
            reference_paiement=form.cleaned_data["reference_paiement"],
            preuve_paiement=form.cleaned_data.get("preuve_paiement"),
            utilisateur=request.user,
        )
        messages.success(request, "Votre demande de paiement a ete envoyee. Elle sera activee apres validation.")
        return redirect("subscription_overview")

    plans = get_commercial_plans_queryset(include_free=False, paid_only=True).order_by("prix", "nom")
    duration_options = get_subscription_payment_duration_options()
    context = {
        "entreprise": entreprise,
        "currency_code": get_currency_code(entreprise),
        "form": form,
        "plans": plans,
        "duration_options": duration_options,
        "pricing_matrix": build_subscription_pricing_matrix(entreprise=entreprise, plans=plans),
        "whatsapp_link": f"https://wa.me/{DEFAULT_WHATSAPP_NUMBER}?text={quote(DEFAULT_WHATSAPP_MESSAGE)}",
    }
    return render(request, "core/subscription_payment_form.html", context)


@permission_required("subscription.view")
def subscription_plan_list(request):
    entreprise = get_user_entreprise_or_raise(request.user)
    subscription = refresh_subscription_status(entreprise)
    plans = list(get_commercial_plans_queryset().order_by("prix", "nom"))
    plan_order = {"free": 0, "starter": 1, "pro": 2, "premium": 3, "business": 3}
    plans.sort(key=lambda plan: (plan_order.get(normalize_plan_code(plan), 99), plan.prix, plan.nom))
    plan_cards = []
    for plan in plans:
        price_info = get_plan_price_for_company(plan, entreprise)
        plan_cards.append(
            {
                "plan": plan,
                "price_info": price_info,
                "features": get_plan_feature_summary(plan),
                "quota_profile": get_plan_quota_profile(plan),
                "is_current": bool(subscription and subscription.plan_id == plan.id),
                "is_free": plan.prix <= 0,
            }
        )
    pending_requests = get_subscription_payments_by_entreprise(entreprise).filter(
        statut=PaiementAbonnement.Statut.EN_ATTENTE,
        source_taux="demande_plan",
    )
    pending_plan_ids = set(pending_requests.values_list("plan_id", flat=True))

    if request.method == "POST":
        plan = get_commercial_plans_queryset(include_free=False, paid_only=True).filter(id=request.POST.get("plan_id")).first()
        if plan is None:
            messages.error(request, "Plan indisponible.")
        else:
            try:
                create_subscription_plan_request(entreprise=entreprise, plan=plan, utilisateur=request.user)
                messages.success(request, f"Votre demande pour le plan {plan.nom} a ete envoyee au super admin.")
                return redirect("subscription_plan_list")
            except ValueError as exc:
                messages.error(request, str(exc))

    return render(
        request,
        "core/subscription_plan_list.html",
        {
            "entreprise": entreprise,
            "subscription": subscription or get_current_subscription(entreprise),
            "plans": plans,
            "plan_cards": plan_cards,
            "pending_plan_ids": pending_plan_ids,
            "whatsapp_link": f"https://wa.me/{DEFAULT_WHATSAPP_NUMBER}?text={quote(DEFAULT_WHATSAPP_MESSAGE)}",
        },
    )


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
                validate_subscription_payment(
                    paiement=paiement,
                    super_admin=request.user,
                    notes_validation=request.POST.get("notes_validation") or "",
                )
                messages.success(request, f"Le paiement a ete valide et l'abonnement a ete active pour {paiement.entreprise.nom}.")
                return redirect("super_admin_dashboard")
            if action == "refuse_payment":
                paiement = get_subscription_payment_for_super_admin(request.POST.get("paiement_id"))
                refuse_subscription_payment(
                    paiement=paiement,
                    super_admin=request.user,
                    notes_validation=request.POST.get("notes_validation") or "",
                )
                messages.success(request, f"Le paiement a ete refuse pour {paiement.entreprise.nom}.")
                return redirect("super_admin_dashboard")

            return _handle_super_admin_subscription_action(request, redirect_name="super_admin_dashboard")
        except ValueError as exc:
            messages.error(request, str(exc))

        return redirect("super_admin_dashboard")

    refresh_all_subscription_statuses(utilisateur=request.user)
    search = (request.GET.get("q") or "").strip()
    selected_statut = (request.GET.get("statut") or "").strip()
    context = {
        "counts": get_super_admin_subscription_counts(),
        "entreprises": get_super_admin_entreprise_queryset(search=search or None, statut=selected_statut or None),
        "plans": get_commercial_plans_queryset().order_by("prix", "nom"),
        "selected_search": search,
        "selected_statut": selected_statut,
        "statut_choices": AbonnementEntreprise.Statut.choices,
        "pending_payments": get_pending_subscription_payments(),
    }
    return render(request, "core/super_admin_dashboard.html", context)


@permission_required("superadmin.view")
def super_admin_subscription_list(request):
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        try:
            if action == "validate_payment":
                paiement = get_subscription_payment_for_super_admin(request.POST.get("paiement_id"))
                validate_subscription_payment(
                    paiement=paiement,
                    super_admin=request.user,
                    notes_validation=request.POST.get("notes_validation") or "",
                )
                messages.success(request, f"La demande a ete validee et l'abonnement a ete active pour {paiement.entreprise.nom}.")
                return redirect("super_admin_subscription_list")
            if action == "refuse_payment":
                paiement = get_subscription_payment_for_super_admin(request.POST.get("paiement_id"))
                refuse_subscription_payment(
                    paiement=paiement,
                    super_admin=request.user,
                    notes_validation=request.POST.get("notes_validation") or "",
                )
                messages.success(request, f"La demande a ete refusee pour {paiement.entreprise.nom}.")
                return redirect("super_admin_subscription_list")
            if action == "validate_plan_request":
                entreprise = get_entreprise_for_super_admin(request.POST.get("entreprise_id"))
                validate_subscription_plan_request(entreprise=entreprise, super_admin=request.user)
                messages.success(request, f"Demande de plan validee pour {entreprise.nom}. En attente de paiement manuel si necessaire.")
                return redirect("super_admin_subscription_list")
            if action == "refuse_plan_request":
                entreprise = get_entreprise_for_super_admin(request.POST.get("entreprise_id"))
                refuse_subscription_plan_request(
                    entreprise=entreprise,
                    super_admin=request.user,
                    notes_validation=request.POST.get("notes_validation") or "",
                )
                messages.success(request, f"Demande de plan refusee pour {entreprise.nom}.")
                return redirect("super_admin_subscription_list")
            return _handle_super_admin_subscription_action(request, redirect_name="super_admin_subscription_list")
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("super_admin_subscription_list")

    refresh_all_subscription_statuses(utilisateur=request.user)
    search = (request.GET.get("q") or "").strip()
    selected_statut = (request.GET.get("statut") or "").strip()
    today = timezone.localdate()
    entreprises = get_super_admin_entreprise_queryset(search=search or None, statut=selected_statut or None)
    for entreprise in entreprises:
        subscription = getattr(entreprise, "abonnement_entreprise", None)
        if subscription and subscription.date_fin:
            entreprise.subscription_days_remaining_display = f"{max((subscription.date_fin - today).days, 0)} jour(s)"
        else:
            entreprise.subscription_days_remaining_display = "-"
        pending_plan_request = get_pending_subscription_plan_request(entreprise)
        if pending_plan_request is not None:
            entreprise.last_payment_id = pending_plan_request.id
            entreprise.last_payment_status = pending_plan_request.statut
            entreprise.last_payment_source = pending_plan_request.source_taux
            entreprise.last_payment_plan_name = pending_plan_request.plan.nom
            entreprise.last_payment_reference = pending_plan_request.reference_paiement
            entreprise.last_payment_created_at = pending_plan_request.date_creation

    context = {
        "entreprises": entreprises,
        "plans": get_commercial_plans_queryset().order_by("prix", "nom"),
        "selected_search": search,
        "selected_statut": selected_statut,
        "statut_choices": AbonnementEntreprise.Statut.choices,
    }
    return render(request, "core/super_admin_subscription_list.html", context)


@permission_required("superadmin.view")
def super_admin_subscription_manual_payment(request, entreprise_id):
    entreprise = get_entreprise_for_super_admin(entreprise_id)
    subscription = getattr(entreprise, "abonnement_entreprise", None)
    form = ManualSubscriptionPaymentForm(request.POST or None, entreprise=entreprise)

    if request.method == "POST":
        if form.is_valid():
            try:
                _, updated_subscription = register_manual_subscription_payment(
                    entreprise=entreprise,
                    plan=form.cleaned_data["plan"],
                    montant=form.cleaned_data["montant"],
                    devise=form.cleaned_data["devise"],
                    methode_paiement=form.cleaned_data["methode_paiement"],
                    reference_paiement=form.cleaned_data.get("reference_paiement", ""),
                    periode_jours=form.cleaned_data["periode_jours"],
                    date_paiement=form.cleaned_data.get("date_paiement"),
                    montant_usd=form.cleaned_data.get("montant_usd"),
                    taux_change_reference=form.cleaned_data.get("taux_change_reference"),
                    super_admin=request.user,
                )
                messages.success(
                    request,
                    f"Paiement enregistre pour {entreprise.nom}. Nouvelle expiration : {updated_subscription.date_fin:%d/%m/%Y}.",
                )
                return redirect("super_admin_subscription_list")
            except ValueError as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, "Veuillez corriger les informations du paiement.")

    return render(
        request,
        "core/super_admin_subscription_manual_payment.html",
        {
            "entreprise": entreprise,
            "subscription": subscription,
            "form": form,
        },
    )


@permission_required("superadmin.view")
def super_admin_user_list(request):
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        target_user = User.objects.select_related("entreprise").filter(id=request.POST.get("user_id")).first()
        if target_user is None:
            messages.error(request, "Utilisateur introuvable.")
            return redirect("super_admin_user_list")
        if target_user.id == request.user.id and action == "deactivate_user":
            messages.error(request, "Vous ne pouvez pas desactiver votre propre compte super admin.")
            return redirect("super_admin_user_list")

        if action == "deactivate_user":
            target_user.is_active = False
            target_user.save(update_fields=["is_active"])
            _record_super_admin_user_action(target_user=target_user, admin_user=request.user, action="utilisateur_desactive")
            messages.success(request, f"Utilisateur desactive : {target_user.username}.")
        elif action == "reactivate_user":
            target_user.is_active = True
            target_user.save(update_fields=["is_active"])
            _record_super_admin_user_action(target_user=target_user, admin_user=request.user, action="utilisateur_reactive")
            messages.success(request, f"Utilisateur reactive : {target_user.username}.")
        else:
            messages.error(request, "Action utilisateur inconnue.")
        return redirect("super_admin_user_list")

    selected_role = (request.GET.get("role") or "").strip()
    selected_entreprise = (request.GET.get("entreprise") or "").strip()
    selected_status = (request.GET.get("status") or "").strip()
    search = (request.GET.get("q") or "").strip()

    users = User.objects.select_related("entreprise").order_by("id")
    if selected_role:
        users = users.filter(role=selected_role)
    if selected_entreprise:
        users = users.filter(entreprise_id=selected_entreprise)
    if selected_status == "active":
        users = users.filter(is_active=True)
    elif selected_status == "inactive":
        users = users.filter(is_active=False)
    if search:
        users = users.filter(
            models.Q(email__icontains=search)
            | models.Q(username__icontains=search)
            | models.Q(first_name__icontains=search)
            | models.Q(last_name__icontains=search)
        )

    return render(
        request,
        "core/super_admin_user_list.html",
        {
            "users": users,
            "role_choices": User.Role.choices,
            "entreprises": Entreprise.objects.order_by("nom", "id"),
            "selected_role": selected_role,
            "selected_entreprise": selected_entreprise,
            "selected_status": selected_status,
            "selected_search": search,
        },
    )


@permission_required("superadmin.view")
def super_admin_audit_list(request):
    selected_entreprise = (request.GET.get("entreprise") or "").strip()
    selected_user = (request.GET.get("utilisateur") or "").strip()
    selected_module = (request.GET.get("module") or "").strip()
    selected_action = (request.GET.get("action") or "").strip()
    selected_date_from = (request.GET.get("date_from") or "").strip()
    selected_date_to = (request.GET.get("date_to") or "").strip()
    search = (request.GET.get("q") or "").strip()

    logs = ActivityLog.objects.select_related("entreprise", "utilisateur").order_by("-date_creation", "-id")
    if selected_entreprise:
        logs = logs.filter(entreprise_id=selected_entreprise)
    if selected_user:
        logs = logs.filter(utilisateur_id=selected_user)
    if selected_module:
        logs = logs.filter(module=selected_module)
    if selected_action:
        logs = logs.filter(action=selected_action)
    date_from = parse_date(selected_date_from) if selected_date_from else None
    date_to = parse_date(selected_date_to) if selected_date_to else None
    if date_from:
        logs = logs.filter(date_creation__date__gte=date_from)
    if date_to:
        logs = logs.filter(date_creation__date__lte=date_to)
    if search:
        logs = logs.filter(
            models.Q(description__icontains=search)
            | models.Q(action__icontains=search)
            | models.Q(module__icontains=search)
            | models.Q(objet_type__icontains=search)
            | models.Q(utilisateur__username__icontains=search)
            | models.Q(utilisateur__email__icontains=search)
            | models.Q(entreprise__nom__icontains=search)
        )

    paginator = Paginator(logs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "core/super_admin_audit_list.html",
        {
            "page_obj": page_obj,
            "logs": page_obj.object_list,
            "entreprises": Entreprise.objects.order_by("nom", "id"),
            "users": User.objects.order_by("username", "id"),
            "modules": ActivityLog.objects.order_by("module").values_list("module", flat=True).distinct(),
            "actions": ActivityLog.objects.order_by("action").values_list("action", flat=True).distinct(),
            "selected_entreprise": selected_entreprise,
            "selected_user": selected_user,
            "selected_module": selected_module,
            "selected_action": selected_action,
            "selected_date_from": selected_date_from,
            "selected_date_to": selected_date_to,
            "selected_search": search,
        },
    )


@permission_required("superadmin.view")
def super_admin_settings(request):
    settings = PlatformSettings.get_solo()
    form = PlatformSettingsForm(request.POST or None, instance=settings)

    if request.method == "POST" and form.is_valid():
        platform_settings = form.save(commit=False)
        changed_fields = list(form.changed_data)
        if changed_fields:
            platform_settings.save(update_fields=changed_fields)
        messages.success(request, "Parametres plateforme mis a jour.")
        return redirect("super_admin_settings")

    return render(
        request,
        "core/super_admin_settings.html",
        {
            "form": form,
            "platform_settings": settings,
        },
    )


@permission_required("superadmin.view")
def super_admin_exchange_rate_list(request):
    selected_source = (request.GET.get("source") or "").strip().upper()
    selected_target = (request.GET.get("target") or "").strip().upper()
    manual_form = ExchangeRateManualForm()

    if request.method == "POST":
        if (request.POST.get("action") or "").strip() == "manual_rate":
            manual_form = ExchangeRateManualForm(request.POST)
            if manual_form.is_valid():
                manual_form.save()
                messages.success(request, "Taux manuel enregistre.")
                return redirect("super_admin_exchange_rate_list")
            messages.error(request, "Veuillez corriger le taux manuel.")
        else:
            source = (request.POST.get("source") or "").strip().upper()
            target = (request.POST.get("target") or "").strip().upper()
            try:
                get_exchange_rate(source, target)
                messages.success(request, f"Taux {source} -> {target} rafraichi ou recupere depuis le cache.")
            except ExchangeRateUnavailable as exc:
                messages.error(request, str(exc))
            return redirect("super_admin_exchange_rate_list")

    rates = ExchangeRate.objects.all()
    if selected_source:
        rates = rates.filter(devise_source=selected_source)
    if selected_target:
        rates = rates.filter(devise_cible=selected_target)
    rates = rates.order_by("-date_taux", "-fetched_at", "-id")[:100]

    return render(
        request,
        "core/super_admin_exchange_rate_list.html",
        {
            "rates": rates,
            "selected_source": selected_source,
            "selected_target": selected_target,
            "manual_form": manual_form,
        },
    )


@permission_required("superadmin.view")
def super_admin_company_list(request):
    search = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    include_inactive = status in {"", "inactive"}
    entreprises = get_super_admin_entreprise_queryset(
        search=search or None,
        include_inactive=include_inactive,
    )
    if status == "active":
        entreprises = entreprises.filter(is_active=True)
    elif status == "inactive":
        entreprises = entreprises.filter(is_active=False)

    return render(
        request,
        "core/super_admin_company_list.html",
        {
            "entreprises": entreprises,
            "selected_search": search,
            "selected_status": status,
        },
    )


@permission_required("superadmin.view")
def super_admin_company_deactivate(request, entreprise_id):
    entreprise = get_entreprise_for_super_admin(entreprise_id)

    if request.method == "POST":
        try:
            deactivate_company_for_super_admin(
                entreprise=entreprise,
                confirmation_name=request.POST.get("confirmation_name") or "",
                utilisateur=request.user,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Entreprise desactivee : {entreprise.nom}. Les donnees sont conservees.")
            return redirect("super_admin_company_list")

    return render(
        request,
        "core/super_admin_company_deactivate.html",
        {
            "entreprise": entreprise,
            "critical_counts": {
                "users": entreprise.user_set.count(),
                "clients": _safe_related_count(entreprise, "client_set"),
                "factures": _safe_related_count(entreprise, "factures"),
                "services": _safe_related_count(entreprise, "service_set"),
                "depenses": _safe_related_count(entreprise, "depenses"),
                "produits": _safe_related_count(entreprise, "produits"),
                "apprenants": _safe_related_count(entreprise, "apprenants"),
                "ecritures": _safe_related_count(entreprise, "ecritures_comptables"),
                "payments": entreprise.paiements_abonnement.count() if hasattr(entreprise, "paiements_abonnement") else 0,
                "logs": entreprise.activity_logs.count() if hasattr(entreprise, "activity_logs") else 0,
            },
        },
    )
