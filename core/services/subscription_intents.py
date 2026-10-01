from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.audit import record_audit_event
from core.models import IntentionAbonnement, PaiementAbonnement
from core.services.subscription import (
    FREE_PLAN_CODE,
    OFFICIAL_PAID_PLAN_CODES,
    get_commercial_plans_queryset,
    get_current_subscription,
    normalize_plan_code,
)

BILLING_CYCLE_MONTHLY = "monthly"
BILLING_CYCLE_YEARLY = "yearly"
BILLING_CYCLE_TO_DURATION = {
    BILLING_CYCLE_MONTHLY: PaiementAbonnement.Duree.MENSUEL,
    BILLING_CYCLE_YEARLY: PaiementAbonnement.Duree.ANNUEL,
    PaiementAbonnement.Duree.MENSUEL: PaiementAbonnement.Duree.MENSUEL,
    PaiementAbonnement.Duree.ANNUEL: PaiementAbonnement.Duree.ANNUEL,
}
DURATION_TO_BILLING_CYCLE = {
    PaiementAbonnement.Duree.MENSUEL: BILLING_CYCLE_MONTHLY,
    PaiementAbonnement.Duree.ANNUEL: BILLING_CYCLE_YEARLY,
}
ACTIVE_INTENT_STATUSES = (
    IntentionAbonnement.Statut.EN_ATTENTE,
    IntentionAbonnement.Statut.PAIEMENT_INITIE,
)
FAILED_PAYMENT_STATUSES = (
    PaiementAbonnement.Statut.REFUSE,
    PaiementAbonnement.Statut.ANNULE,
    PaiementAbonnement.Statut.ECHOUE,
    PaiementAbonnement.Statut.EXPIRE,
)
PENDING_PAYMENT_STATUSES = (
    PaiementAbonnement.Statut.EN_ATTENTE,
    PaiementAbonnement.Statut.EN_COURS,
)
PAID_PAYMENT_STATUSES = (
    PaiementAbonnement.Statut.VALIDE,
    PaiementAbonnement.Statut.APPROUVEE,
)
DEFAULT_INTENT_EXPIRATION_DAYS = 14


@dataclass(frozen=True)
class PublicSubscriptionSelection:
    is_valid: bool
    is_paid: bool
    plan: object = None
    duree: str = ""
    plan_code: str = ""
    billing_cycle: str = ""
    reason: str = ""


@dataclass(frozen=True)
class SubscriptionIntentResumeResult:
    status: str
    intention: Optional[IntentionAbonnement] = None
    paiement: Optional[PaiementAbonnement] = None
    checkout_url: str = ""
    message: str = ""


class SubscriptionIntentStatus:
    NO_INTENT = "no_intent"
    CHECKOUT = "checkout"
    CONSUMED = "consumed"
    FAILED_PAYMENT = "failed_payment"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    EXPIRED = "expired"
    PENDING = "pending"


def get_subscription_intent_expiration_date():
    days = getattr(settings, "JOATHAM_SUBSCRIPTION_INTENT_EXPIRATION_DAYS", DEFAULT_INTENT_EXPIRATION_DAYS)
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = DEFAULT_INTENT_EXPIRATION_DAYS
    return timezone.now() + timedelta(days=max(1, days))


def normalize_billing_cycle(value):
    raw_value = (value or "").strip().lower().replace("-", "_")
    if raw_value in {"monthly", "month", "mensuel"}:
        return BILLING_CYCLE_MONTHLY
    if raw_value in {"yearly", "annual", "annuel", "year"}:
        return BILLING_CYCLE_YEARLY
    return ""


def duration_from_billing_cycle(value):
    billing_cycle = normalize_billing_cycle(value)
    if not billing_cycle:
        return ""
    return BILLING_CYCLE_TO_DURATION[billing_cycle]


def billing_cycle_from_duration(duree):
    return DURATION_TO_BILLING_CYCLE.get(duree, "")


def get_signup_plan_params(plan_code, billing_cycle):
    code = normalize_plan_code(plan_code)
    billing = normalize_billing_cycle(billing_cycle)
    if not code or code == FREE_PLAN_CODE:
        return {"plan": FREE_PLAN_CODE, "billing": BILLING_CYCLE_MONTHLY}
    if code not in OFFICIAL_PAID_PLAN_CODES or not billing:
        return {"plan": "", "billing": ""}
    return {"plan": code, "billing": billing}


def resolve_public_subscription_selection(*, plan_code, billing_cycle):
    code = normalize_plan_code(plan_code)
    billing = normalize_billing_cycle(billing_cycle)
    if not code or code == FREE_PLAN_CODE:
        return PublicSubscriptionSelection(
            is_valid=True,
            is_paid=False,
            plan_code=FREE_PLAN_CODE,
            billing_cycle=BILLING_CYCLE_MONTHLY,
        )
    if code not in OFFICIAL_PAID_PLAN_CODES:
        return PublicSubscriptionSelection(is_valid=False, is_paid=False, plan_code=code, reason="invalid_plan")
    if not billing:
        return PublicSubscriptionSelection(is_valid=False, is_paid=False, plan_code=code, reason="invalid_billing")

    plan = None
    for candidate in get_commercial_plans_queryset(include_free=False, paid_only=True):
        if normalize_plan_code(candidate) == code:
            plan = candidate
            break
    if plan is None:
        return PublicSubscriptionSelection(is_valid=False, is_paid=False, plan_code=code, billing_cycle=billing, reason="missing_plan")

    return PublicSubscriptionSelection(
        is_valid=True,
        is_paid=True,
        plan=plan,
        duree=duration_from_billing_cycle(billing),
        plan_code=code,
        billing_cycle=billing,
    )


@transaction.atomic
def create_subscription_intention_from_public_selection(*, entreprise, utilisateur, plan_code, billing_cycle, source="landing"):
    selection = resolve_public_subscription_selection(plan_code=plan_code, billing_cycle=billing_cycle)
    if not selection.is_valid or not selection.is_paid:
        return None

    # Only pending intentions without a provider payment are superseded here. Once a payment exists,
    # the payment/webhook remains the source of truth and must not be silently overwritten.
    cancellable_intentions = IntentionAbonnement.objects.select_for_update().filter(
        entreprise=entreprise,
        statut=IntentionAbonnement.Statut.EN_ATTENTE,
        paiement__isnull=True,
    )
    reusable_intention = cancellable_intentions.filter(plan=selection.plan, duree=selection.duree).order_by("-date_creation", "-id").first()
    if reusable_intention is not None:
        reusable_intention.utilisateur = utilisateur
        reusable_intention.source = source
        reusable_intention.date_expiration = get_subscription_intent_expiration_date()
        reusable_intention.save(update_fields=["utilisateur", "source", "date_expiration", "date_modification"])
        return reusable_intention

    now = timezone.now()
    cancellable_intentions.update(statut=IntentionAbonnement.Statut.ANNULEE, date_consommation=now)
    intention = IntentionAbonnement.objects.create(
        entreprise=entreprise,
        utilisateur=utilisateur,
        plan=selection.plan,
        duree=selection.duree,
        statut=IntentionAbonnement.Statut.EN_ATTENTE,
        source=source,
        date_expiration=get_subscription_intent_expiration_date(),
    )
    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="subscription_intent_created",
        module="subscription",
        objet_type="IntentionAbonnement",
        objet_id=intention.id,
        description=f"Intention abonnement creee pour le plan {selection.plan.nom}.",
        metadata={"plan_id": selection.plan.id, "duree": selection.duree, "source": source},
    )
    return intention


def get_active_subscription_intention_for_user(user):
    entreprise = getattr(user, "entreprise", None)
    if entreprise is None:
        return None
    _expire_stale_waiting_intentions(entreprise=entreprise)
    return (
        IntentionAbonnement.objects.select_related("entreprise", "utilisateur", "plan", "paiement")
        .filter(entreprise=entreprise, statut__in=ACTIVE_INTENT_STATUSES)
        .order_by("-date_creation", "-id")
        .first()
    )


def _expire_stale_waiting_intentions(*, entreprise):
    now = timezone.now()
    IntentionAbonnement.objects.filter(
        entreprise=entreprise,
        statut=IntentionAbonnement.Statut.EN_ATTENTE,
        paiement__isnull=True,
        date_expiration__isnull=False,
        date_expiration__lt=now,
    ).update(statut=IntentionAbonnement.Statut.EXPIREE, date_consommation=now)


@transaction.atomic
def resume_subscription_intention_payment(*, intention, provider, utilisateur=None):
    if intention is None:
        return SubscriptionIntentResumeResult(status=SubscriptionIntentStatus.NO_INTENT)
    intention = (
        IntentionAbonnement.objects.select_for_update()
        .select_related("entreprise", "plan", "paiement")
        .get(pk=intention.pk)
    )
    if intention.statut not in ACTIVE_INTENT_STATUSES:
        return SubscriptionIntentResumeResult(status=intention.statut, intention=intention)

    if (
        intention.statut == IntentionAbonnement.Statut.EN_ATTENTE
        and intention.paiement_id is None
        and intention.date_expiration
        and intention.date_expiration < timezone.now()
    ):
        intention.statut = IntentionAbonnement.Statut.EXPIREE
        intention.date_consommation = timezone.now()
        intention.save(update_fields=["statut", "date_consommation", "date_modification"])
        return SubscriptionIntentResumeResult(status=SubscriptionIntentStatus.EXPIRED, intention=intention)

    current_subscription = get_current_subscription(intention.entreprise)
    if current_subscription and current_subscription.actif and current_subscription.plan_id == intention.plan_id:
        _mark_intention_consumed_locked(intention, paiement=intention.paiement)
        return SubscriptionIntentResumeResult(status=SubscriptionIntentStatus.CONSUMED, intention=intention, paiement=intention.paiement)

    paiement = intention.paiement
    if paiement is not None:
        if paiement.statut in PAID_PAYMENT_STATUSES:
            _mark_intention_consumed_locked(intention, paiement=paiement)
            return SubscriptionIntentResumeResult(status=SubscriptionIntentStatus.CONSUMED, intention=intention, paiement=paiement)
        if paiement.statut in PENDING_PAYMENT_STATUSES:
            return SubscriptionIntentResumeResult(
                status=SubscriptionIntentStatus.CHECKOUT if paiement.checkout_url else SubscriptionIntentStatus.PENDING,
                intention=intention,
                paiement=paiement,
                checkout_url=paiement.checkout_url,
            )
        if paiement.statut in FAILED_PAYMENT_STATUSES:
            return SubscriptionIntentResumeResult(
                status=SubscriptionIntentStatus.FAILED_PAYMENT,
                intention=intention,
                paiement=paiement,
                message="Le paiement precedent n'a pas ete confirme.",
            )

    if not provider:
        return SubscriptionIntentResumeResult(status=SubscriptionIntentStatus.PROVIDER_UNAVAILABLE, intention=intention)

    from core.services.subscription_payments import create_automatic_subscription_payment_request

    paiement = create_automatic_subscription_payment_request(
        entreprise=intention.entreprise,
        plan=intention.plan,
        duree=intention.duree,
        provider=provider,
        utilisateur=utilisateur or intention.utilisateur,
    )
    intention.paiement = paiement
    intention.statut = IntentionAbonnement.Statut.PAIEMENT_INITIE
    intention.save(update_fields=["paiement", "statut", "date_modification"])
    return SubscriptionIntentResumeResult(
        status=SubscriptionIntentStatus.CHECKOUT if paiement.checkout_url else SubscriptionIntentStatus.PENDING,
        intention=intention,
        paiement=paiement,
        checkout_url=paiement.checkout_url,
    )


def mark_subscription_intention_consumed_for_payment(paiement):
    if paiement is None:
        return 0
    with transaction.atomic():
        intentions = IntentionAbonnement.objects.select_for_update().filter(
            paiement=paiement,
            statut__in=ACTIVE_INTENT_STATUSES,
        )
        count = 0
        for intention in intentions:
            _mark_intention_consumed_locked(intention, paiement=paiement)
            count += 1
        if count:
            return count
        fallback_intentions = IntentionAbonnement.objects.select_for_update().filter(
            entreprise=paiement.entreprise,
            plan=paiement.plan,
            duree=paiement.duree,
            paiement__isnull=True,
            statut__in=ACTIVE_INTENT_STATUSES,
        )
        for intention in fallback_intentions:
            _mark_intention_consumed_locked(intention, paiement=paiement)
            count += 1
        return count


def _mark_intention_consumed_locked(intention, *, paiement=None):
    intention.statut = IntentionAbonnement.Statut.CONSOMMEE
    if paiement is not None:
        intention.paiement = paiement
    intention.date_consommation = intention.date_consommation or timezone.now()
    intention.save(update_fields=["statut", "paiement", "date_consommation", "date_modification"])