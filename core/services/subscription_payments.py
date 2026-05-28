import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from core.audit import record_audit_event
from core.models import PaiementAbonnement
from core.services.exchange_rates import get_platform_currency
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
def create_automatic_subscription_payment_request(
    *,
    entreprise,
    plan,
    duree,
    provider="test",
    utilisateur=None,
):
    if plan is None or not getattr(plan, "actif", False) or normalize_plan_code(plan) not in OFFICIAL_PAID_PLAN_CODES:
        raise ValueError("Plan indisponible.")

    estimate = build_subscription_payment_estimate(entreprise=entreprise, plan=plan, duree=duree)
    external_reference = _build_unique_external_reference()
    amount_usd = estimate["amount_usd"].quantize(Decimal("0.01"))
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
        amount_expected=amount_usd,
        paid_currency=get_platform_currency(),
        created_by=utilisateur,
    )

    provider_client = get_payment_provider(paiement.provider)
    checkout = provider_client.create_payment(paiement)
    paiement.provider_checkout_id = checkout.provider_checkout_id
    paiement.checkout_url = checkout.checkout_url
    paiement.provider_status = checkout.provider_status
    paiement.save(update_fields=["provider_checkout_id", "checkout_url", "provider_status"])

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
            "currency": get_platform_currency(),
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

    with transaction.atomic():
        paiement = (
            PaiementAbonnement.objects.select_for_update()
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
            raise PaymentProviderVerificationError("Paiement abonnement introuvable.")

        if _is_duplicate_webhook(paiement, verified_payment):
            paiement.raw_provider_payload = verified_payment.raw_payload
            paiement.provider_status = verified_payment.provider_status
            if verified_payment.event_id:
                paiement.last_webhook_event_id = verified_payment.event_id
            paiement.verified_at = timezone.now()
            paiement.save(update_fields=["raw_provider_payload", "provider_status", "last_webhook_event_id", "verified_at"])
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

        rejection_reason = _get_confirmation_rejection_reason(paiement, verified_payment)
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
        paiement.periode_debut = paiement.periode_debut or timezone.localdate()
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
        paiement = PaiementAbonnement.objects.select_for_update().select_related("entreprise", "plan").get(pk=paiement.pk)
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
    raise PaymentProviderError("Impossible de generer une reference paiement unique.")


def _store_webhook_snapshot(paiement, verified_payment):
    paiement.raw_provider_payload = verified_payment.raw_payload
    paiement.provider_status = verified_payment.provider_status
    paiement.verified_at = timezone.now()
    paiement.amount_paid = verified_payment.amount
    paiement.paid_currency = verified_payment.currency
    if verified_payment.event_id:
        paiement.last_webhook_event_id = verified_payment.event_id
    paiement.save(
        update_fields=[
            "raw_provider_payload",
            "provider_status",
            "verified_at",
            "amount_paid",
            "paid_currency",
            "last_webhook_event_id",
        ]
    )


def _is_duplicate_webhook(paiement, verified_payment):
    if verified_payment.event_id and paiement.last_webhook_event_id == verified_payment.event_id:
        return True
    if verified_payment.status == "paid" and paiement.statut == PaiementAbonnement.Statut.VALIDE:
        return True
    if verified_payment.status == "failed" and paiement.statut == PaiementAbonnement.Statut.ECHOUE:
        return True
    if verified_payment.status == "cancelled" and paiement.statut == PaiementAbonnement.Statut.ANNULE:
        return True
    if verified_payment.status == "expired" and paiement.statut == PaiementAbonnement.Statut.EXPIRE:
        return True
    return False


def _get_confirmation_rejection_reason(paiement, verified_payment):
    expected_amount = (paiement.amount_expected or paiement.montant_usd or paiement.montant).quantize(Decimal("0.01"))
    if verified_payment.amount != expected_amount:
        return "Montant paye different du montant attendu."
    expected_currency = get_platform_currency().upper()
    if verified_payment.currency != expected_currency:
        return "Devise payee differente de la devise attendue."
    if not verified_payment.provider_transaction_id:
        return "Identifiant transaction provider manquant."
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
