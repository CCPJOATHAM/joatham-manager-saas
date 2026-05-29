import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime


class PaymentProviderError(Exception):
    """Base error for payment provider operations."""


class PaymentProviderVerificationError(PaymentProviderError):
    """Raised when a webhook cannot be trusted."""


@dataclass(frozen=True)
class ProviderPaymentSession:
    provider_checkout_id: str
    checkout_url: str
    provider_status: str = "pending"


@dataclass(frozen=True)
class VerifiedWebhookPayment:
    external_reference: str
    event_id: str
    status: str
    amount: Optional[Decimal]
    currency: str
    provider_transaction_id: str
    provider_status: str
    raw_payload: dict
    paid_at: Optional[object] = None


class BasePaymentProvider:
    provider_code = ""

    def create_payment(self, payment_request):
        raise NotImplementedError

    def verify_webhook(self, request):
        raise NotImplementedError

    def fetch_transaction_status(self, provider_transaction_id):
        raise NotImplementedError


INTERNAL_PROVIDER_CODES = {"", "manual", "test"}


class TestPaymentProvider(BasePaymentProvider):
    provider_code = "test"

    def _ensure_enabled(self):
        if not (getattr(settings, "JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER", False) or getattr(settings, "DEBUG", False)):
            raise PaymentProviderError("Le provider de test n'est pas active.")

    def create_payment(self, payment_request):
        self._ensure_enabled()
        reference = payment_request.external_reference
        return ProviderPaymentSession(
            provider_checkout_id=f"test-checkout-{reference}",
            checkout_url=f"/abonnement/paiement/retour/?reference={reference}",
            provider_status="pending",
        )

    def verify_webhook(self, request):
        self._ensure_enabled()
        expected_signature = getattr(settings, "JOATHAM_TEST_PAYMENT_WEBHOOK_SECRET", "test-secret")
        received_signature = request.headers.get("X-JOATHAM-TEST-SIGNATURE", "")
        if not expected_signature or received_signature != expected_signature:
            raise PaymentProviderVerificationError("Signature webhook invalide.")

        try:
            payload = json.loads((request.body or b"{}").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PaymentProviderVerificationError("Payload webhook invalide.") from exc

        reference = (payload.get("external_reference") or payload.get("reference") or "").strip()
        if not reference:
            raise PaymentProviderVerificationError("Reference paiement manquante.")

        raw_status = (payload.get("status") or "").strip().lower()
        status = _normalize_provider_status(raw_status)
        paid_at = _parse_provider_datetime(payload.get("paid_at"))
        return VerifiedWebhookPayment(
            external_reference=reference,
            event_id=(payload.get("event_id") or "").strip(),
            status=status,
            amount=_parse_decimal(payload.get("amount")),
            currency=(payload.get("currency") or "").strip().upper(),
            provider_transaction_id=(payload.get("provider_transaction_id") or payload.get("transaction_id") or "").strip(),
            provider_status=raw_status or status,
            raw_payload=payload,
            paid_at=paid_at,
        )

    def fetch_transaction_status(self, provider_transaction_id):
        self._ensure_enabled()
        return {"provider_transaction_id": provider_transaction_id, "status": "unknown"}


def _normalize_provider_status(status):
    if status in {"paid", "success", "succeeded", "confirmed", "valide"}:
        return "paid"
    if status in {"failed", "failure", "refused", "refuse", "echoue"}:
        return "failed"
    if status in {"cancelled", "canceled", "annule"}:
        return "cancelled"
    if status in {"expired", "expire"}:
        return "expired"
    if status in {"processing", "pending", "en_cours", "en_attente"}:
        return "processing"
    return status or "unknown"


def _parse_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise PaymentProviderVerificationError("Montant webhook invalide.")


def _parse_provider_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def get_payment_provider(provider_code):
    normalized = (provider_code or "").strip().lower()
    if normalized == TestPaymentProvider.provider_code:
        return TestPaymentProvider()
    raise PaymentProviderError("Provider de paiement non supporte.")


def get_requested_payment_provider_code():
    configured = (
        getattr(settings, "JOATHAM_PAYMENT_PROVIDER", "")
        or getattr(settings, "JOATHAM_AUTOMATIC_PAYMENT_PROVIDER", "")
        or ""
    )
    return configured.strip().lower()


def get_automatic_payment_provider_code(*, allow_test=False):
    if not getattr(settings, "JOATHAM_AUTO_PAYMENT_ENABLED", False):
        return ""
    provider_code = get_requested_payment_provider_code()
    if provider_code == "test":
        if (
            allow_test
            and getattr(settings, "DEBUG", False)
            and getattr(settings, "JOATHAM_ENABLE_TEST_PAYMENT_PROVIDER", False)
        ):
            return provider_code
        return ""
    if provider_code in INTERNAL_PROVIDER_CODES:
        return ""
    return provider_code


def is_real_automatic_payment_provider_configured():
    provider_code = get_automatic_payment_provider_code()
    if not provider_code:
        return False
    try:
        get_payment_provider(provider_code)
    except PaymentProviderError:
        return False
    return provider_code not in INTERNAL_PROVIDER_CODES
