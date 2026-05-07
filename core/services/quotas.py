from calendar import monthrange
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.services.subscription import FREE_PLAN_INVOICE_LIMIT, FREE_PLAN_USER_LIMIT, is_entreprise_on_free_plan
from joatham_users.models import Entreprise


PREMIUM_REQUIRED_MESSAGE = "Cette fonctionnalite est reservee aux plans premium."
FREE_PLAN_PRODUCT_LIMIT = 50
FREE_PLAN_EXPENSE_MONTHLY_LIMIT = 50


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


def assert_invoice_quota_available(entreprise, *, as_of=None):
    if not is_entreprise_on_free_plan(entreprise):
        return

    _lock_entreprise_for_quota(entreprise)
    invoice_count = get_monthly_invoice_count(entreprise, as_of=as_of)
    if invoice_count >= FREE_PLAN_INVOICE_LIMIT:
        raise PlanQuotaExceeded(
            f"{PREMIUM_REQUIRED_MESSAGE} Le plan gratuit permet jusqu'a {FREE_PLAN_INVOICE_LIMIT} factures par mois."
        )


def assert_user_quota_available(entreprise):
    if not is_entreprise_on_free_plan(entreprise):
        return

    _lock_entreprise_for_quota(entreprise)
    User = get_user_model()
    user_count = User.objects.filter(entreprise=entreprise).count()
    if user_count >= FREE_PLAN_USER_LIMIT:
        raise PlanQuotaExceeded(
            f"{PREMIUM_REQUIRED_MESSAGE} Le plan gratuit est limite a un seul utilisateur proprietaire."
        )


def assert_product_quota_available(entreprise):
    if not is_entreprise_on_free_plan(entreprise):
        return

    _lock_entreprise_for_quota(entreprise)
    product_count = get_product_count(entreprise)
    if product_count >= FREE_PLAN_PRODUCT_LIMIT:
        raise PlanQuotaExceeded(
            f"{PREMIUM_REQUIRED_MESSAGE} Le plan gratuit permet jusqu'a {FREE_PLAN_PRODUCT_LIMIT} produits."
        )


def assert_expense_quota_available(entreprise, *, as_of=None):
    if not is_entreprise_on_free_plan(entreprise):
        return

    _lock_entreprise_for_quota(entreprise)
    expense_count = get_monthly_expense_count(entreprise, as_of=as_of)
    if expense_count >= FREE_PLAN_EXPENSE_MONTHLY_LIMIT:
        raise PlanQuotaExceeded(
            f"{PREMIUM_REQUIRED_MESSAGE} Le plan gratuit permet jusqu'a {FREE_PLAN_EXPENSE_MONTHLY_LIMIT} depenses par mois."
        )
