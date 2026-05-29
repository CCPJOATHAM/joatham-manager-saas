import json
import hmac
import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
import requests


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
CINETPAY_PROVIDER_CODE = "cinetpay"
CINETPAY_NOTIFICATION_HMAC_FIELDS = (
    "cpm_site_id",
    "cpm_trans_id",
    "cpm_trans_date",
    "cpm_amount",
    "cpm_currency",
    "signature",
    "payment_method",
    "cel_phone_num",
    "cpm_phone_prefixe",
    "cpm_language",
    "cpm_version",
    "cpm_payment_config",
    "cpm_page_action",
    "cpm_custom",
    "cpm_designation",
    "cpm_error_message",
)


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


class CinetPayPaymentProvider(BasePaymentProvider):
    provider_code = CINETPAY_PROVIDER_CODE

    def __init__(self):
        self.site_id = _payment_setting("CINETPAY_SITE_ID", "JOATHAM_PAYMENT_PUBLIC_KEY")
        self.apikey = _payment_setting("CINETPAY_APIKEY", "JOATHAM_PAYMENT_SECRET_KEY")
        self.secret_key = _payment_setting("CINETPAY_SECRET_KEY", "JOATHAM_PAYMENT_WEBHOOK_SECRET")
        self.payment_url = _payment_setting("CINETPAY_PAYMENT_URL", default="https://api-checkout.cinetpay.com/v2/payment")
        self.check_url = _payment_setting("CINETPAY_PAYMENT_CHECK_URL", default="https://api-checkout.cinetpay.com/v2/payment/check")
        self.notify_url = _payment_setting("JOATHAM_PAYMENT_CALLBACK_URL")
        self.return_url = _payment_setting("JOATHAM_PAYMENT_RETURN_URL")
        self.channels = _payment_setting("JOATHAM_PAYMENT_CHANNELS", "CINETPAY_CHANNELS", default="MOBILE_MONEY") or "MOBILE_MONEY"
        self.currency = (_payment_setting("CINETPAY_CURRENCY", "JOATHAM_PAYMENT_CURRENCY") or "USD").upper()
        self.timeout = getattr(settings, "JOATHAM_PAYMENT_HTTP_TIMEOUT", 20)

    def is_configured(self):
        return all([self.site_id, self.apikey, self.secret_key, self.notify_url, self.return_url])

    def _ensure_configured(self):
        if not self.is_configured():
            raise PaymentProviderError("Paiement automatique CinetPay non configure.")

    def create_payment(self, payment_request):
        self._ensure_configured()
        amount = _as_cinetpay_amount(payment_request.amount_expected or payment_request.montant_usd or payment_request.montant)
        payload = {
            "apikey": self.apikey,
            "site_id": self.site_id,
            "transaction_id": payment_request.external_reference,
            "amount": amount,
            "currency": self.currency,
            "description": _safe_cinetpay_description(f"Abonnement JOATHAM Manager {payment_request.plan.nom}"),
            "notify_url": self.notify_url,
            "return_url": f"{self.return_url}?reference={payment_request.external_reference}",
            "channels": self.channels,
            "metadata": payment_request.external_reference,
            "lang": "fr",
            "invoice_data": {
                "Plan": payment_request.plan.nom,
                "Reference": payment_request.external_reference,
                "Entreprise": payment_request.entreprise.nom,
            },
        }
        response_payload = _post_json(self.payment_url, payload, timeout=self.timeout)
        data = response_payload.get("data") or {}
        checkout_url = (data.get("payment_url") or "").strip()
        if not checkout_url:
            raise PaymentProviderError("CinetPay n'a pas retourne d'URL de paiement.")
        return ProviderPaymentSession(
            provider_checkout_id=(data.get("payment_token") or response_payload.get("api_response_id") or "").strip(),
            checkout_url=checkout_url,
            provider_status=(response_payload.get("code") or response_payload.get("message") or "created"),
        )

    def verify_webhook(self, request):
        self._ensure_configured()
        payload = _request_payload(request)
        transaction_id = (payload.get("cpm_trans_id") or "").strip()
        if not transaction_id:
            raise PaymentProviderVerificationError("Reference CinetPay manquante.")
        posted_site_id = (payload.get("cpm_site_id") or "").strip()
        if posted_site_id and posted_site_id != self.site_id:
            raise PaymentProviderVerificationError("Site CinetPay invalide.")
        self._verify_hmac_token(request, payload)
        verified = self.fetch_transaction_status(transaction_id)
        verified_payload = dict(verified.raw_payload)
        verified_payload["notification"] = payload
        return VerifiedWebhookPayment(
            external_reference=verified.external_reference,
            event_id=verified.event_id,
            status=verified.status,
            amount=verified.amount,
            currency=verified.currency,
            provider_transaction_id=verified.provider_transaction_id,
            provider_status=verified.provider_status,
            raw_payload=verified_payload,
            paid_at=verified.paid_at,
        )

    def fetch_transaction_status(self, provider_transaction_id):
        self._ensure_configured()
        transaction_id = (provider_transaction_id or "").strip()
        if not transaction_id:
            raise PaymentProviderVerificationError("Reference CinetPay manquante.")
        response_payload = _post_json(
            self.check_url,
            {
                "apikey": self.apikey,
                "site_id": self.site_id,
                "transaction_id": transaction_id,
            },
            timeout=self.timeout,
        )
        data = response_payload.get("data") or {}
        status = _normalize_cinetpay_status(data.get("status") or response_payload.get("message"))
        provider_transaction_id = (
            data.get("operator_id")
            or response_payload.get("api_response_id")
            or transaction_id
        )
        paid_at = _parse_provider_datetime(data.get("payment_date"))
        return VerifiedWebhookPayment(
            external_reference=transaction_id,
            event_id=str(response_payload.get("api_response_id") or ""),
            status=status,
            amount=_parse_decimal(data.get("amount")),
            currency=(data.get("currency") or "").strip().upper(),
            provider_transaction_id=str(provider_transaction_id).strip(),
            provider_status=(data.get("status") or response_payload.get("message") or status),
            raw_payload=response_payload,
            paid_at=paid_at,
        )

    def _verify_hmac_token(self, request, payload):
        received_token = (request.headers.get("x-token") or "").strip()
        if not received_token:
            raise PaymentProviderVerificationError("Token HMAC CinetPay manquant.")
        data = "".join(str(payload.get(field, "")) for field in CINETPAY_NOTIFICATION_HMAC_FIELDS)
        expected_token = hmac.new(self.secret_key.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received_token, expected_token):
            raise PaymentProviderVerificationError("Token HMAC CinetPay invalide.")


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


def _normalize_cinetpay_status(status):
    normalized = (status or "").strip().upper()
    if normalized == "ACCEPTED":
        return "paid"
    if normalized in {"REFUSED", "CANCELLED", "CANCELED", "TRANSACTION_CANCEL"}:
        return "failed"
    if normalized in {"WAITING_FOR_CUSTOMER", "PENDING", "PROCESSING"}:
        return "processing"
    return _normalize_provider_status(normalized.lower())


def _payment_setting(*names, default=""):
    for name in names:
        value = getattr(settings, name, None)
        if value not in (None, ""):
            return str(value).strip()
    return str(default or "").strip()


def _request_payload(request):
    if request.POST:
        return {key: request.POST.get(key, "") for key in request.POST.keys()}
    try:
        return json.loads((request.body or b"{}").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PaymentProviderVerificationError("Payload webhook invalide.") from exc


def _as_cinetpay_amount(value):
    amount = Decimal(value or "0").quantize(Decimal("0.01"))
    if amount <= 0:
        raise PaymentProviderError("Montant CinetPay invalide.")
    if amount == amount.to_integral_value():
        return int(amount)
    return str(amount)


def _safe_cinetpay_description(value):
    return "".join(char for char in str(value) if char not in "#/,$_&").strip()[:100]


def _post_json(url, payload, *, timeout):
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "User-Agent": "JOATHAM-Manager/1.0"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise PaymentProviderError("CinetPay est temporairement indisponible.") from exc
    try:
        response_payload = response.json()
    except ValueError as exc:
        raise PaymentProviderError("Reponse CinetPay invalide.") from exc
    if response.status_code >= 400:
        raise PaymentProviderError(response_payload.get("message") or "CinetPay a refuse la requete.")
    return response_payload


def get_payment_provider(provider_code):
    normalized = (provider_code or "").strip().lower()
    if normalized == TestPaymentProvider.provider_code:
        return TestPaymentProvider()
    if normalized == CinetPayPaymentProvider.provider_code:
        return CinetPayPaymentProvider()
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
    try:
        provider = get_payment_provider(provider_code)
    except PaymentProviderError:
        return ""
    if hasattr(provider, "is_configured") and not provider.is_configured():
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
