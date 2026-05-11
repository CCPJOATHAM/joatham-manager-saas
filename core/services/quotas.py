from calendar import monthrange
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.services.subscription import (
    FREE_PLAN_INVOICE_LIMIT,
    FREE_PLAN_USER_LIMIT,
    FREE_PLAN_CLIENT_LIMIT,
    get_plan_quota_profile,
    get_subscription_for_entreprise,
    is_entreprise_on_free_plan,
)
from joatham_users.models import Entreprise


PREMIUM_REQUIRED_MESSAGE = "Cette fonctionnalite n'est pas incluse dans votre plan actuel."
FREE_PLAN_PRODUCT_LIMIT = 30
FREE_PLAN_EXPENSE_MONTHLY_LIMIT = 20
FREE_PLAN_CASHBOX_LIMIT = 1


class PlanQuotaExceeded(ValueError):
    pass


def _lock_entreprise_for_quota(entreprise):
    if entreprise is None:
        return
    Entreprise.objects.select_for_update().filter(pk=entreprise.pk).exists()


def _month_bounds(as_of=None):
    current = as_of or timezone.localdate()
    month_start = current.replace(day=1)
    last_day = monthrange(current.year, current.month)[1]
    month_end = current.replace(day=last_day) + timedelta(days=1)
    return month_start, month_end


def get_monthly_invoice_count(entreprise, *, as_of=None):
    from joatham_billing.models import Facture

    month_start, month_end = _month_bounds(as_of=as_of)
    return Facture.objects.filter(
        entreprise=entreprise,
        date__date__gte=month_start,
        date__date__lt=month_end,
    ).count()


def get_product_count(entreprise):
    from joatham_products.models import Produit

    return Produit.objects.filter(entreprise=entreprise).count()


def get_monthly_expense_count(entreprise, *, as_of=None):
    from joatham_depenses.models import Depense

    month_start, month_end = _month_bounds(as_of=as_of)
    return Depense.objects.filter(
        entreprise=entreprise,
        date__date__gte=month_start,
        date__date__lt=month_end,
    ).count()


def get_active_cashbox_count(entreprise):
    from joatham_caisse.models import Caisse

    return Caisse.objects.filter(entreprise=entreprise, est_active=True).count()


def get_client_count(entreprise):
    from joatham_clients.models import Client

    return Client.objects.filter(entreprise=entreprise).count()


def get_current_plan_for_quota(entreprise):
    subscription = get_subscription_for_entreprise(entreprise)
    return getattr(subscription, "plan", None) if subscription is not None else None


def get_plan_quota_limit(entreprise, quota_name, *, plan_field=None):
    plan = get_current_plan_for_quota(entreprise)
    if plan is None:
        return None
    if plan_field:
        field_value = getattr(plan, plan_field, None)
        if field_value is not None:
            return field_value
    profile = get_plan_quota_profile(plan)
    if quota_name in profile:
        return profile[quota_name]
    if is_entreprise_on_free_plan(entreprise):
        return {
            "max_factures_mois": FREE_PLAN_INVOICE_LIMIT,
            "max_clients": FREE_PLAN_CLIENT_LIMIT,
            "max_produits": FREE_PLAN_PRODUCT_LIMIT,
            "max_depenses_mois": FREE_PLAN_EXPENSE_MONTHLY_LIMIT,
            "max_caisses": FREE_PLAN_CASHBOX_LIMIT,
            "max_utilisateurs": FREE_PLAN_USER_LIMIT,
        }.get(quota_name)
    return None


def _format_quota_limit(limit):
    return "illimite" if limit is None else str(limit)


def assert_invoice_quota_available(entreprise, *, as_of=None):
    limit = get_plan_quota_limit(entreprise, "max_factures_mois", plan_field="max_factures_mois")
    if limit is None:
        return

    _lock_entreprise_for_quota(entreprise)
    invoice_count = get_monthly_invoice_count(entreprise, as_of=as_of)
    if invoice_count >= limit:
        raise PlanQuotaExceeded(
            f"{PREMIUM_REQUIRED_MESSAGE} Votre plan permet jusqu'a {_format_quota_limit(limit)} factures par mois."
        )


def assert_user_quota_available(entreprise):
    limit = get_plan_quota_limit(entreprise, "max_utilisateurs", plan_field="max_utilisateurs")
    if limit is None:
        return

    _lock_entreprise_for_quota(entreprise)
    User = get_user_model()
    user_count = User.objects.filter(entreprise=entreprise).count()
    if user_count >= limit:
        raise PlanQuotaExceeded(
            f"{PREMIUM_REQUIRED_MESSAGE} Votre plan permet jusqu'a {_format_quota_limit(limit)} utilisateur(s)."
        )


def assert_product_quota_available(entreprise):
    limit = get_plan_quota_limit(entreprise, "max_produits")
    if limit is None:
        return

    _lock_entreprise_for_quota(entreprise)
    product_count = get_product_count(entreprise)
    if product_count >= limit:
        raise PlanQuotaExceeded(
            f"{PREMIUM_REQUIRED_MESSAGE} Votre plan permet jusqu'a {_format_quota_limit(limit)} produits."
        )


def assert_expense_quota_available(entreprise, *, as_of=None):
    limit = get_plan_quota_limit(entreprise, "max_depenses_mois")
    if limit is None:
        return

    _lock_entreprise_for_quota(entreprise)
    expense_count = get_monthly_expense_count(entreprise, as_of=as_of)
    if expense_count >= limit:
        raise PlanQuotaExceeded(
            f"{PREMIUM_REQUIRED_MESSAGE} Votre plan permet jusqu'a {_format_quota_limit(limit)} depenses par mois."
        )


def assert_cashbox_quota_available(entreprise):
    limit = get_plan_quota_limit(entreprise, "max_caisses")
    if limit is None:
        return

    _lock_entreprise_for_quota(entreprise)
    cashbox_count = get_active_cashbox_count(entreprise)
    if cashbox_count >= limit:
        raise PlanQuotaExceeded(
            f"{PREMIUM_REQUIRED_MESSAGE} Votre plan permet jusqu'a {_format_quota_limit(limit)} caisse(s) active(s)."
        )


def assert_client_quota_available(entreprise):
    limit = get_plan_quota_limit(entreprise, "max_clients", plan_field="max_clients")
    if limit is None:
        return

    _lock_entreprise_for_quota(entreprise)
    client_count = get_client_count(entreprise)
    if client_count >= limit:
        raise PlanQuotaExceeded(
            f"{PREMIUM_REQUIRED_MESSAGE} Votre plan permet jusqu'a {_format_quota_limit(limit)} clients."
        )
