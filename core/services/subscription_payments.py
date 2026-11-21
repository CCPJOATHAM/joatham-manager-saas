from django.utils.translation import gettext_lazy
import uuid
from datetime import timedelta
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.db import transaction
from django.utils import timezone

from core.audit import record_audit_event
from core.models import PaiementAbonnement
from joatham_users.models import Entreprise
from core.services.exchange_rates import ExchangeRateUnavailable, convert_amount, get_platform_currency
from core.services.payment_providers import (
    PaymentProviderError,
    PaymentProviderVerificationError,
    get_payment_provider,
)
from core.services.subscription import (
    OFFICIAL_PAID_PLAN_CODES,
    activate_subscription_for_entreprise,
    build_subscription_payment_estimate,
    get_subscription_payment_duration_days,
    normalize_plan_code,
)


@dataclass(frozen=True)
class SubscriptionPaymentWebhookResult:
    paiement: Optional[PaiementAbonnement]
    status: str
    message: str
    activated: bool = False
    duplicate: bool = False
    rejected: bool = False


def generate_external_reference():
    return f"SUB-{uuid.uuid4().hex}"


@transaction.atomic
def resume_or_create_automatic_payment(**kwargs):
    """Repeated checkout clicks resume the outstanding order, never charge twice."""
    Entreprise.objects.select_for_update().get(pk=kwargs["entreprise"].pk)
    pending = PaiementAbonnement.objects.filter(
        entreprise=kwargs["entreprise"], plan=kwargs["plan"], duree=kwargs["duree"],
        provider=kwargs["provider"], methode_paiement=PaiementAbonnement.Methode.AUTOMATIQUE,
        statut__in=[PaiementAbonnement.Statut.EN_ATTENTE, PaiementAbonnement.Statut.EN_COURS],
    ).exclude(checkout_url="").order_by("date_creation", "pk").first()
    return pending or create_automatic_subscription_payment_request(**kwargs)


def reconcile_subscription_payment(paiement):
    """An owner can request a server-side status check, never supply its result."""
    if paiement.statut == PaiementAbonnement.Statut.VALIDE:
        return paiement
    if paiement.provider != "cinetpay" or paiement.methode_paiement != PaiementAbonnement.Methode.AUTOMATIQUE:
        raise PaymentProviderError(gettext_lazy("Ce paiement nécessite une vérification manuelle par notre équipe."))
    provider = get_payment_provider(paiement.provider)
    if paiement.provider_notify_token or "checkout" in (paiement.raw_provider_payload or {}):
        verified = provider.fetch_transaction_status(paiement.external_reference)
    else:
        # Existing Checkout v2 sessions continue to use their original API.
        provider._ensure_legacy_webhook_configured()
        verified = provider._fetch_checkout_v2_transaction_status(paiement.external_reference)
    if verified.external_reference != paiement.external_reference:
        raise PaymentProviderVerificationError("Payment reference mismatch")
    return apply_verified_subscription_payment(paiement.provider, verified).paiement


@transaction.atomic
def create_automatic_subscription_payment_request(
    *,
    entreprise,
    plan,
    duree,
    provider="test",
    utilisateur=None,
):
    if plan is None or not getattr(plan, "actif", False) or normalize_plan_code(plan) not in OFFICIAL_PAID_PLAN_CODES:
        raise ValueError(gettext_lazy("Plan indisponible."))

    # All payment writers lock the company before payments/intentions. This also
    # serializes renewals when the company has no subscription row yet.
    Entreprise.objects.select_for_update().get(pk=entreprise.pk)

    estimate = build_subscription_payment_estimate(entreprise=entreprise, plan=plan, duree=duree)
    amount_usd = estimate["amount_usd"].quantize(Decimal("0.01"))
    external_reference = _build_unique_external_reference()
    provider_client = get_payment_provider((provider or "").strip().lower())
    expected_amount, expected_currency = _get_provider_expected_amount_and_currency(
        provider_client=provider_client,
        amount_usd=amount_usd,
        estimate=estimate,
    )
    paiement = PaiementAbonnement.objects.create(
        entreprise=entreprise,
        plan=plan,
        duree=duree,
        montant=amount_usd,
        montant_usd=amount_usd,
        devise_entreprise=estimate["currency_code"],
        montant_devise_locale_estime=estimate["estimated_amount"],
        taux_change_reference=estimate["exchange_rate"],
        source_taux=estimate["exchange_source"],
        date_taux=estimate.get("exchange_rate_date"),
        statut=PaiementAbonnement.Statut.EN_ATTENTE,
        methode_paiement=PaiementAbonnement.Methode.AUTOMATIQUE,
        provider=(provider or "").strip().lower(),
        provider_status="pending",
        external_reference=external_reference,
        reference_paiement=external_reference,
        amount_expected=expected_amount,
        paid_currency=expected_currency,
        created_by=utilisateur,
    )

    checkout = provider_client.create_payment(paiement)
    paiement.provider_checkout_id = checkout.provider_checkout_id
    paiement.checkout_url = checkout.checkout_url
    paiement.provider_status = checkout.provider_status
    update_fields = ["provider_checkout_id", "checkout_url", "provider_status"]
    if checkout.provider_transaction_id:
        paiement.provider_transaction_id = checkout.provider_transaction_id
        update_fields.append("provider_transaction_id")
    if checkout.notify_token:
        paiement.provider_notify_token = checkout.notify_token
        update_fields.append("provider_notify_token")
    if checkout.raw_payload:
        paiement.raw_provider_payload = {"checkout": checkout.raw_payload}
        update_fields.append("raw_provider_payload")
    paiement.save(update_fields=update_fields)

    record_audit_event(
        entreprise=entreprise,
        utilisateur=utilisateur,
        action="subscription_payment_auto_created",
        module="subscription",
        objet_type="PaiementAbonnement",
        objet_id=paiement.id,
        description=f"Paiement automatique cree pour le plan {plan.nom}.",
        metadata={
            "provider": paiement.provider,
            "external_reference": paiement.external_reference,
            "amount_expected": str(paiement.amount_expected),
            "currency": paiement.paid_currency,
            "amount_usd": str(paiement.montant_usd),
            "duree": duree,
        },
    )
    return paiement


def handle_subscription_payment_webhook(provider, request):
    provider_client = get_payment_provider(provider)
    try:
        verified_payment = provider_client.verify_webhook(request)
    except PaymentProviderVerificationError:
        record_audit_event(
            entreprise=None,
            utilisateur=None,
            action="subscription_payment_webhook_rejected",
            module="subscription",
            objet_type="PaiementAbonnement",
            description="Webhook paiement abonnement rejete avant identification.",
            metadata={"provider": provider, "reason": "verification_failed"},
        )
        raise

    return apply_verified_subscription_payment(provider, verified_payment)


def apply_verified_subscription_payment(provider, verified_payment):
    """Apply only a provider-authenticated, server-checked result."""
    with transaction.atomic():
        company_id = PaiementAbonnement.objects.filter(
            external_reference=verified_payment.external_reference,
            provider=(provider or "").strip().lower(),
        ).values_list("entreprise_id", flat=True).first()
        if company_id:
            Entreprise.objects.select_for_update().get(pk=company_id)
        paiement = (
            PaiementAbonnement.objects.select_for_update(of=("self",))
            .select_related("entreprise", "plan")
            .filter(external_reference=verified_payment.external_reference, provider=(provider or "").strip().lower())
            .first()
        )
        if paiement is None:
            record_audit_event(
                entreprise=None,
                utilisateur=None,
                action="subscription_payment_webhook_rejected",
                module="subscription",
                objet_type="PaiementAbonnement",
                description="Webhook paiement abonnement rejete pour reference inconnue.",
                metadata={
                    "provider": provider,
                    "external_reference": verified_payment.external_reference,
                    "event_id": verified_payment.event_id,
                },
            )
            raise PaymentProviderVerificationError(gettext_lazy("Paiement abonnement introuvable."))

        expected_amount = (paiement.amount_expected or paiement.montant_usd or paiement.montant).quantize(Decimal("0.01"))
        expected_currency = (paiement.paid_currency or get_platform_currency()).upper()

        if _is_duplicate_webhook(paiement, verified_payment):
            # Confirmed financial data is immutable, including on a late failure.
            if paiement.statut in {PaiementAbonnement.Statut.VALIDE, PaiementAbonnement.Statut.APPROUVEE}:
                from core.services.subscription_intents import mark_subscription_intention_consumed_for_payment

                mark_subscription_intention_consumed_for_payment(paiement)
            record_audit_event(
                entreprise=paiement.entreprise,
                utilisateur=None,
                action="subscription_payment_webhook_duplicate",
                module="subscription",
                objet_type="PaiementAbonnement",
                objet_id=paiement.id,
                description="Webhook paiement abonnement deja traite.",
                metadata={
                    "provider": provider,
                    "external_reference": paiement.external_reference,
                    "event_id": verified_payment.event_id,
                    "status": paiement.statut,
                },
            )
            return SubscriptionPaymentWebhookResult(
                paiement=paiement,
                status=paiement.statut,
                message="Webhook deja traite.",
                activated=False,
                duplicate=True,
            )

        _store_webhook_snapshot(paiement, verified_payment)

        if verified_payment.status in {"failed", "cancelled", "expired"}:
            target_status = {
                "cancelled": PaiementAbonnement.Statut.ANNULE,
                "expired": PaiementAbonnement.Statut.EXPIRE,
            }.get(verified_payment.status, PaiementAbonnement.Statut.ECHOUE)
            _mark_automatic_payment_failed_locked(
                paiement=paiement,
                reason=f"Statut provider: {verified_payment.status}",
                provider_status=verified_payment.provider_status,
                statut=target_status,
            )
            return SubscriptionPaymentWebhookResult(
                paiement=paiement,
                status=paiement.statut,
                message="Paiement non confirme.",
            )

        if verified_payment.status != "paid":
            paiement.statut = PaiementAbonnement.Statut.EN_COURS
            paiement.save(update_fields=["statut"])
            return SubscriptionPaymentWebhookResult(
                paiement=paiement,
                status=paiement.statut,
                message="Paiement en cours.",
            )

        rejection_reason = _get_confirmation_rejection_reason(
            paiement,
            verified_payment,
            expected_amount=expected_amount,
            expected_currency=expected_currency,
        )
        if rejection_reason:
            _mark_automatic_payment_failed_locked(
                paiement=paiement,
                reason=rejection_reason,
                provider_status=verified_payment.provider_status,
            )
            record_audit_event(
                entreprise=paiement.entreprise,
                utilisateur=None,
                action="subscription_payment_webhook_rejected",
                module="subscription",
                objet_type="PaiementAbonnement",
                objet_id=paiement.id,
                description="Webhook paiement abonnement rejete apres verification.",
                metadata={
                    "provider": provider,
                    "external_reference": paiement.external_reference,
                    "reason": rejection_reason,
                    "amount_paid": str(verified_payment.amount),
                    "currency": verified_payment.currency,
                },
            )
            return SubscriptionPaymentWebhookResult(
                paiement=paiement,
                status=paiement.statut,
                message=rejection_reason,
                rejected=True,
            )

        duration_days = get_subscription_payment_duration_days(paiement.duree)
        subscription = activate_subscription_for_entreprise(
            entreprise=paiement.entreprise,
            plan=paiement.plan,
            utilisateur=None,
            duration_days=duration_days,
            prolong_existing=True,
        )
        now = timezone.now()
        paiement.statut = PaiementAbonnement.Statut.VALIDE
        paiement.date_validation = now
        paiement.date_paiement = verified_payment.paid_at or now
        paiement.paid_at = verified_payment.paid_at or now
        paiement.verified_at = now
        paiement.periode_debut = subscription.date_fin - timedelta(days=duration_days)
        paiement.periode_fin = subscription.date_fin
        paiement.amount_paid = verified_payment.amount
        paiement.paid_currency = verified_payment.currency
        paiement.provider_transaction_id = verified_payment.provider_transaction_id or None
        paiement.failure_reason = ""
        paiement.save(
            update_fields=[
                "statut",
                "date_validation",
                "date_paiement",
                "paid_at",
                "verified_at",
                "periode_debut",
                "periode_fin",
                "amount_paid",
                "paid_currency",
                "provider_transaction_id",
                "failure_reason",
            ]
        )
        record_audit_event(
            entreprise=paiement.entreprise,
            utilisateur=None,
            action="subscription_payment_auto_confirmed",
            module="subscription",
            objet_type="PaiementAbonnement",
            objet_id=paiement.id,
            description=f"Paiement automatique confirme pour le plan {paiement.plan.nom}.",
            metadata={
                "provider": provider,
                "external_reference": paiement.external_reference,
                "provider_transaction_id": paiement.provider_transaction_id,
                "amount_paid": str(paiement.amount_paid),
                "currency": paiement.paid_currency,
            },
        )
        from core.services.subscription_intents import mark_subscription_intention_consumed_for_payment

        mark_subscription_intention_consumed_for_payment(paiement)
        record_audit_event(
            entreprise=paiement.entreprise,
            utilisateur=None,
            action="subscription_auto_activated",
            module="subscription",
            objet_type="AbonnementEntreprise",
            objet_id=subscription.id,
            description=f"Abonnement active automatiquement sur le plan {paiement.plan.nom}.",
            metadata={
                "paiement_id": paiement.id,
                "plan_id": paiement.plan_id,
                "date_fin": str(subscription.date_fin),
            },
        )
        return SubscriptionPaymentWebhookResult(
            paiement=paiement,
            status=paiement.statut,
            message="Paiement confirme et abonnement active.",
            activated=True,
        )


def mark_automatic_payment_failed(*, paiement, reason, provider_status="", raw_provider_payload=None, event_id=""):
    with transaction.atomic():
        Entreprise.objects.select_for_update().get(pk=paiement.entreprise_id)
        paiement = PaiementAbonnement.objects.select_for_update(of=("self",)).select_related("entreprise", "plan").get(pk=paiement.pk)
        if paiement.statut == PaiementAbonnement.Statut.VALIDE:
            return paiement
        if raw_provider_payload is not None:
            paiement.raw_provider_payload = raw_provider_payload
        if event_id:
            paiement.last_webhook_event_id = event_id
        _mark_automatic_payment_failed_locked(paiement=paiement, reason=reason, provider_status=provider_status)
        return paiement


def _build_unique_external_reference():
    for _ in range(10):
        reference = generate_external_reference()
        if not PaiementAbonnement.objects.filter(external_reference=reference).exists():
            return reference
    raise PaymentProviderError(gettext_lazy('Impossible de générer une référence paiement unique.'))


def _get_provider_expected_amount_and_currency(*, provider_client, amount_usd, estimate):
    platform_currency = get_platform_currency().upper()
    provider_currency = (getattr(provider_client, "currency", "") or platform_currency).upper()
    if not provider_currency or provider_currency == platform_currency:
        return (
            _normalize_provider_expected_amount(
                provider_client=provider_client,
                amount=amount_usd,
                currency=platform_currency,
            ),
            platform_currency,
        )

    estimate_currency = (estimate.get("currency_code") or "").upper()
    estimated_amount = estimate.get("estimated_amount")
    if estimate_currency == provider_currency and estimated_amount is not None:
        amount = Decimal(str(estimated_amount)).quantize(Decimal("0.01"))
        return (
            _normalize_provider_expected_amount(
                provider_client=provider_client,
                amount=amount,
                currency=provider_currency,
            ),
            provider_currency,
        )

    try:
        conversion = convert_amount(amount_usd, platform_currency, provider_currency)
    except ExchangeRateUnavailable as exc:
        raise PaymentProviderError((gettext_lazy('Conversion %(value_1)s->%(value_2)s indisponible pour CinetPay.') % {'value_1': platform_currency, 'value_2': provider_currency})) from exc
    amount = conversion.amount.quantize(Decimal("0.01"))
    return (
        _normalize_provider_expected_amount(
            provider_client=provider_client,
            amount=amount,
            currency=provider_currency,
        ),
        provider_currency,
    )


def _normalize_provider_expected_amount(*, provider_client, amount, currency):
    if (
        getattr(provider_client, "provider_code", "") == "cinetpay"
        and (currency or "").upper() == "CDF"
    ):
        return Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return amount


def _store_webhook_snapshot(paiement, verified_payment):
    paiement.raw_provider_payload = verified_payment.raw_payload
    paiement.provider_status = verified_payment.provider_status
    paiement.verified_at = timezone.now()
    if verified_payment.event_id:
        paiement.last_webhook_event_id = verified_payment.event_id
    paiement.save(
        update_fields=[
            "raw_provider_payload",
            "provider_status",
            "verified_at",
            "last_webhook_event_id",
        ]
    )


def _is_duplicate_webhook(paiement, verified_payment):
    # A transaction id is not an event-state id: pending -> paid often reuses it.
    if paiement.statut == PaiementAbonnement.Statut.VALIDE:
        return True
    if verified_payment.status == "failed" and paiement.statut == PaiementAbonnement.Statut.ECHOUE:
        return True
    if verified_payment.status == "cancelled" and paiement.statut == PaiementAbonnement.Statut.ANNULE:
        return True
    if verified_payment.status == "expired" and paiement.statut == PaiementAbonnement.Statut.EXPIRE:
        return True
    return False


def _get_confirmation_rejection_reason(paiement, verified_payment, *, expected_amount, expected_currency):
    if verified_payment.amount != expected_amount:
        return "Montant paye different du montant attendu."
    if verified_payment.currency != expected_currency:
        return "Devise payee differente de la devise attendue."
    if not verified_payment.provider_transaction_id:
        return "Identifiant transaction provider manquant."
    if paiement.provider_transaction_id and paiement.provider_transaction_id != verified_payment.provider_transaction_id:
        return "Identifiant transaction provider incoherent."
    duplicate_transaction = (
        PaiementAbonnement.objects.filter(provider_transaction_id=verified_payment.provider_transaction_id)
        .exclude(pk=paiement.pk)
        .exists()
    )
    if duplicate_transaction:
        return "Transaction provider deja associee a un autre paiement."
    return ""


def _mark_automatic_payment_failed_locked(*, paiement, reason, provider_status="", statut=PaiementAbonnement.Statut.ECHOUE):
    paiement.statut = statut
    paiement.failure_reason = (reason or "Paiement automatique echoue.").strip()
    paiement.provider_status = provider_status or paiement.provider_status
    paiement.verified_at = timezone.now()
    paiement.save(update_fields=["statut", "failure_reason", "provider_status", "verified_at"])
    record_audit_event(
        entreprise=paiement.entreprise,
        utilisateur=None,
        action="subscription_payment_auto_failed",
        module="subscription",
        objet_type="PaiementAbonnement",
        objet_id=paiement.id,
        description=f"Paiement automatique echoue pour le plan {paiement.plan.nom}.",
        metadata={
            "provider": paiement.provider,
            "external_reference": paiement.external_reference,
            "reason": paiement.failure_reason,
            "provider_status": paiement.provider_status,
        },
    )
