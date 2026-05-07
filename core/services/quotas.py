from calendar import monthrange
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.services.subscription import FREE_PLAN_INVOICE_LIMIT, FREE_PLAN_USER_LIMIT, is_entreprise_on_free_plan
from joatham_users.models import Entreprise


PREMIUM_REQUIRED_MESSAGE = "Cette fonctionnalite est reservee aux plans premium."


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
