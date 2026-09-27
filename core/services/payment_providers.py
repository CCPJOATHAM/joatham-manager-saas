import json
import hmac
import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

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
    provider_transaction_id: str = ""
    notify_token: str = ""
    raw_payload: Optional[dict] = None


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
CINETPAY_DEFAULT_AUTH_URL = "https://api.cinetpay.net/v1/oauth/login"
CINETPAY_DEFAULT_PAYMENT_URL = "https://api.cinetpay.net/v1/payment"
CINETPAY_DEFAULT_PAYMENT_CHECK_URL = "https://api.cinetpay.net/v1/payment/{merchant_transaction_id}"
CINETPAY_LEGACY_CHECKOUT_V2_PAYMENT_CHECK_URL = "https://api-checkout.cinetpay.com/v2/payment/check"
CINETPAY_ALLOWED_CHANNELS = {"PUSH", "OTP", "QRCODE"}
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
        self.apikey = _payment_setting("CINETPAY_APIKEY", "CINETPAY_API_KEY", "JOATHAM_PAYMENT_SECRET_KEY")
        self.api_password = _payment_setting("CINETPAY_API_PASSWORD", "JOATHAM_PAYMENT_API_PASSWORD")
        self.secret_key = _payment_setting("CINETPAY_SECRET_KEY", "JOATHAM_PAYMENT_WEBHOOK_SECRET")
        self.auth_url = _payment_setting("CINETPAY_AUTH_URL", default=CINETPAY_DEFAULT_AUTH_URL)
        self.payment_url = _payment_setting("CINETPAY_PAYMENT_URL", default=CINETPAY_DEFAULT_PAYMENT_URL)
        self.check_url = _payment_setting("CINETPAY_PAYMENT_CHECK_URL", default=CINETPAY_DEFAULT_PAYMENT_CHECK_URL)
        self.legacy_check_url = _payment_setting(
            "CINETPAY_CHECKOUT_V2_PAYMENT_CHECK_URL",
            "CINETPAY_LEGACY_PAYMENT_CHECK_URL",
            default=CINETPAY_LEGACY_CHECKOUT_V2_PAYMENT_CHECK_URL,
        )
        self.notify_url = _payment_setting("JOATHAM_PAYMENT_CALLBACK_URL")
        self.return_url = _payment_setting("JOATHAM_PAYMENT_RETURN_URL")
        self.channels = _payment_setting("JOATHAM_PAYMENT_CHANNELS", "CINETPAY_CHANNELS", default="MOBILE_MONEY") or "MOBILE_MONEY"
        self.channel = _payment_setting("CINETPAY_CHANNEL", default="PUSH").upper()
        if self.channel not in CINETPAY_ALLOWED_CHANNELS:
            self.channel = "PUSH"
        self.currency = _payment_setting("CINETPAY_CURRENCY", "JOATHAM_PAYMENT_CURRENCY").upper()
        self.timeout = getattr(settings, "JOATHAM_PAYMENT_HTTP_TIMEOUT", 20)

    def missing_configuration(self):
        required_settings = {
            "CINETPAY_APIKEY": self.apikey,
            "CINETPAY_API_PASSWORD": self.api_password,
            "CINETPAY_CURRENCY": self.currency,
            "JOATHAM_PAYMENT_CALLBACK_URL": self.notify_url,
            "JOATHAM_PAYMENT_RETURN_URL": self.return_url,
        }
        return [name for name, value in required_settings.items() if not value]

    def is_configured(self):
        return not self.missing_configuration()

    def _ensure_configured(self):
        if not self.is_configured():
            raise PaymentProviderError("Paiement automatique CinetPay non configure.")

    def create_payment(self, payment_request):
        self._ensure_configured()
        token = self._authenticate()
        amount = _as_cinetpay_amount(payment_request.amount_expected or payment_request.montant_usd or payment_request.montant)
        user = getattr(payment_request, "created_by", None)
        entreprise = payment_request.entreprise
        success_url = _url_with_query(self.return_url, reference=payment_request.external_reference, status="success")
        failed_url = _url_with_query(self.return_url, reference=payment_request.external_reference, status="failed")
        payload = {
            "currency": self.currency,
            "merchant_transaction_id": payment_request.external_reference,
            "amount": amount,
            "lang": "fr",
            "designation": _safe_cinetpay_description(f"Abonnement JOATHAM Manager {payment_request.plan.nom}"),
            "client_email": _client_email(user, entreprise),
            "client_first_name": _client_first_name(user, entreprise),
            "client_last_name": _client_last_name(user, entreprise),
            "success_url": success_url,
            "failed_url": failed_url,
            "notify_url": self.notify_url,
            "channel": self.channel,
            "direct_pay": False,
            "metadata": {
                "reference": payment_request.external_reference,
                "plan": payment_request.plan.nom,
                "entreprise": entreprise.nom,
            },
        }
        phone_number = _client_phone_number(user, entreprise)
        if phone_number:
            payload["client_phone_number"] = phone_number

        response_payload = _post_json(
            self.payment_url,
            payload,
            timeout=self.timeout,
            headers=_bearer_headers(token),
        )
        data = _response_data(response_payload)
        details = data.get("details") if isinstance(data.get("details"), dict) else {}
        checkout_url = _pick(data, details, response_payload, "payment_url", "paymentUrl").strip()
        if not checkout_url:
            raise PaymentProviderError("CinetPay n'a pas retourne d'URL de paiement.")
        return ProviderPaymentSession(
            provider_checkout_id=_pick(data, details, response_payload, "payment_token", "paymentToken").strip(),
            checkout_url=checkout_url,
            provider_status=_pick(data, details, response_payload, "status", "message", "code") or "created",
            provider_transaction_id=_pick(data, details, response_payload, "transaction_id", "transactionId").strip(),
            notify_token=_pick(data, details, response_payload, "notify_token", "notifyToken").strip(),
            raw_payload=_redact_sensitive_payload(response_payload),
        )

    def verify_webhook(self, request):
        payload = _request_payload(request)
        if "cpm_trans_id" in payload:
            self._ensure_legacy_webhook_configured()
            return self._verify_checkout_v2_webhook(request, payload)

        self._ensure_configured()
        merchant_transaction_id = _pick(payload, "merchant_transaction_id", "merchantTransactionId").strip()
        if not merchant_transaction_id:
            raise PaymentProviderVerificationError("Reference CinetPay manquante.")
        notify_token = _pick(payload, "notify_token", "notifyToken").strip()
        if not notify_token:
            raise PaymentProviderVerificationError("Token notification CinetPay manquant.")

        from core.models import PaiementAbonnement

        paiement = (
            PaiementAbonnement.objects.filter(
                external_reference=merchant_transaction_id,
                provider=self.provider_code,
            )
            .only("provider_notify_token")
            .first()
        )
        if paiement is None:
            raise PaymentProviderVerificationError("Paiement abonnement introuvable.")
        expected_notify_token = (paiement.provider_notify_token or "").strip()
        if not expected_notify_token:
            raise PaymentProviderVerificationError("Token notification CinetPay non configure.")
        if not hmac.compare_digest(notify_token, expected_notify_token):
            raise PaymentProviderVerificationError("Token notification CinetPay invalide.")

        verified = self.fetch_transaction_status(merchant_transaction_id)
        if verified.external_reference and verified.external_reference != merchant_transaction_id:
            raise PaymentProviderVerificationError("Reference CinetPay incoherente.")
        verified_payload = dict(verified.raw_payload)
        verified_payload["notification"] = _redact_sensitive_payload(payload)
        return VerifiedWebhookPayment(
            external_reference=merchant_transaction_id,
            event_id=verified.event_id,
            status=verified.status,
            amount=verified.amount,
            currency=verified.currency,
            provider_transaction_id=verified.provider_transaction_id,
            provider_status=verified.provider_status,
            raw_payload=verified_payload,
            paid_at=verified.paid_at,
        )

    def _verify_checkout_v2_webhook(self, request, payload):
        transaction_id = (payload.get("cpm_trans_id") or "").strip()
        if not transaction_id:
            raise PaymentProviderVerificationError("Reference CinetPay manquante.")
        posted_site_id = (payload.get("cpm_site_id") or "").strip()
        if posted_site_id and posted_site_id != self.site_id:
            raise PaymentProviderVerificationError("Site CinetPay invalide.")
        self._verify_hmac_token(request, payload)
        verified = self._fetch_checkout_v2_transaction_status(transaction_id)
        verified_payload = dict(verified.raw_payload)
        verified_payload["notification"] = _redact_sensitive_payload(payload)
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
        merchant_transaction_id = (provider_transaction_id or "").strip()
        if not merchant_transaction_id:
            raise PaymentProviderVerificationError("Reference CinetPay manquante.")
        token = self._authenticate()
        response_payload = _get_json(
            _cinetpay_status_url(self.check_url, merchant_transaction_id),
            timeout=self.timeout,
            headers=_bearer_headers(token),
        )
        data = _response_data(response_payload)
        details = data.get("details") if isinstance(data.get("details"), dict) else {}
        status = _normalize_cinetpay_status(_pick(data, details, response_payload, "status", "payment_status", "message"))
        paid_at = _parse_provider_datetime(_pick(data, details, response_payload, "payment_date", "paid_at", "updated_at"))
        return VerifiedWebhookPayment(
            external_reference=(
                _pick(data, details, response_payload, "merchant_transaction_id", "merchantTransactionId").strip()
                or merchant_transaction_id
            ),
            event_id=_pick(data, details, response_payload, "transaction_id", "transactionId", "event_id").strip(),
            status=status,
            amount=_parse_decimal(_pick(data, details, response_payload, "amount")),
            currency=_pick(data, details, response_payload, "currency").strip().upper(),
            provider_transaction_id=_pick(data, details, response_payload, "transaction_id", "transactionId").strip(),
            provider_status=_pick(data, details, response_payload, "status", "payment_status", "message") or status,
            raw_payload=_redact_sensitive_payload(response_payload),
            paid_at=paid_at,
        )

    def _fetch_checkout_v2_transaction_status(self, provider_transaction_id):
        transaction_id = (provider_transaction_id or "").strip()
        if not transaction_id:
            raise PaymentProviderVerificationError("Reference CinetPay manquante.")
        response_payload = _post_json(
            self.legacy_check_url,
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

    def _authenticate(self):
        response_payload = _post_json(
            self.auth_url,
            {
                "api_key": self.apikey,
                "api_password": self.api_password,
            },
            timeout=self.timeout,
        )
        data = _response_data(response_payload)
        token = _pick(data, response_payload, "access_token", "token").strip()
        if not token:
            raise PaymentProviderError("Authentification CinetPay invalide.")
        return token

    def _ensure_legacy_webhook_configured(self):
        if not self.apikey or not self.site_id or not self.secret_key:
            raise PaymentProviderVerificationError("Configuration CinetPay Checkout v2 incomplete.")

    def _verify_hmac_token(self, request, payload):
        if not self.secret_key:
            raise PaymentProviderVerificationError("Secret HMAC CinetPay non configure.")
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
    if normalized in {"ACCEPTED", "SUCCESS", "SUCCES"}:
        return "paid"
    if normalized in {"CANCELLED", "CANCELED", "TRANSACTION_CANCEL"}:
        return "cancelled"
    if normalized in {"FAILED", "FAILURE", "REFUSED", "INSUFFICIENT_BALANCE"}:
        return "failed"
    if normalized in {"EXPIRED"}:
        return "expired"
    if normalized in {"WAITING_FOR_CUSTOMER", "PENDING", "PROCESSING", "INITIATED"}:
        return "processing"
    return _normalize_provider_status(normalized.lower())


def _payment_setting(*names, default=""):
    for name in names:
        value = getattr(settings, name, None)
        if value not in (None, ""):
            return str(value).strip()
    return str(default or "").strip()


def _payment_setting_presence(*names, default=""):
    for name in names:
        value = getattr(settings, name, None)
        if value not in (None, ""):
            return True, name
    if default not in (None, ""):
        return True, "default"
    return False, ""


def _payment_url_source(name, default):
    value = _payment_setting(name, default=default)
    return value, "default" if value == default else "custom"


def _payment_url_source_label(source):
    if source == "custom":
        return "URL personnalisée"
    return "URL par défaut"


def _safe_diagnostic_url(value):
    url = str(value or "").strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    hostname = parts.hostname or ""
    netloc = hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _url_with_query(url, **params):
    parts = urlsplit(str(url or "").strip())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items() if value not in (None, "")})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _cinetpay_status_url(url_template, merchant_transaction_id):
    encoded_reference = quote(str(merchant_transaction_id or "").strip(), safe="")
    template = str(url_template or CINETPAY_DEFAULT_PAYMENT_CHECK_URL).strip()
    if "{merchant_transaction_id}" in template:
        return template.format(merchant_transaction_id=encoded_reference)
    if "{transaction_id}" in template:
        return template.format(transaction_id=encoded_reference)
    return f"{template.rstrip('/')}/{encoded_reference}"


def _url_looks_like_sandbox(url):
    normalized = str(url or "").strip().lower()
    return any(marker in normalized for marker in ("sandbox", "test", "preprod"))


def _url_looks_like_production(url):
    normalized = str(url or "").strip().lower()
    return bool(normalized) and "cinetpay" in normalized and not _url_looks_like_sandbox(normalized)


def _payment_environment_label(enabled, provider_is_cinetpay, sandbox_setting):
    if not enabled and not provider_is_cinetpay:
        return "Non configuré"
    if not provider_is_cinetpay:
        return "Ambigu" if enabled else "Non configuré"
    if sandbox_setting in (None, ""):
        return "Ambigu"
    return "Sandbox" if bool(sandbox_setting) else "Production"


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


def _client_email(user, entreprise):
    return (
        getattr(user, "email", "")
        or getattr(entreprise, "email", "")
        or "client@joatham.com"
    ).strip()


def _client_first_name(user, entreprise):
    value = (getattr(user, "first_name", "") or getattr(user, "username", "") or getattr(entreprise, "nom", "") or "Client").strip()
    first = value.split()[0] if value.split() else value
    return first if len(first) >= 2 else "Client"


def _client_last_name(user, entreprise):
    value = (getattr(user, "last_name", "") or getattr(entreprise, "nom", "") or "JOATHAM").strip()
    return value if len(value) >= 2 else "JOATHAM"


def _client_phone_number(user, entreprise):
    return (getattr(user, "telephone", "") or getattr(entreprise, "telephone", "") or "").strip()


def _response_data(response_payload):
    data = response_payload.get("data") if isinstance(response_payload, dict) else {}
    return data if isinstance(data, dict) else {}


def _pick(*args):
    sources = [arg for arg in args if isinstance(arg, dict)]
    keys = [arg for arg in args if not isinstance(arg, dict)]
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _bearer_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _redact_sensitive_payload(payload):
    if isinstance(payload, dict):
        sensitive_keys = {
            "api_key",
            "api_password",
            "apikey",
            "password",
            "access_token",
            "accessToken",
            "token",
            "payment_token",
            "paymentToken",
            "notify_token",
            "notifyToken",
        }
        return {
            key: "***" if key in sensitive_keys else _redact_sensitive_payload(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_redact_sensitive_payload(item) for item in payload]
    return payload


def _json_headers(headers=None):
    merged = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "JOATHAM-Manager/1.0",
    }
    if headers:
        merged.update(headers)
    return merged


def _post_json(url, payload, *, timeout, headers=None):
    try:
        response = requests.post(
            url,
            json=payload,
            headers=_json_headers(headers),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise PaymentProviderError("CinetPay est temporairement indisponible.") from exc
    try:
        response_payload = response.json()
    except ValueError as exc:
        raise PaymentProviderError("Reponse CinetPay invalide.") from exc
    if response.status_code >= 400:
        raise PaymentProviderError("CinetPay a refuse la requete.")
    return response_payload


def _get_json(url, *, timeout, headers=None):
    try:
        response = requests.get(
            url,
            headers=_json_headers(headers),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise PaymentProviderError("CinetPay est temporairement indisponible.") from exc
    try:
        response_payload = response.json()
    except ValueError as exc:
        raise PaymentProviderError("Reponse CinetPay invalide.") from exc
    if response.status_code >= 400:
        raise PaymentProviderError("CinetPay a refuse la requete.")
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


def get_automatic_payment_configuration_diagnostic():
    provider = get_requested_payment_provider_code()
    enabled = bool(getattr(settings, "JOATHAM_AUTO_PAYMENT_ENABLED", False))
    provider_is_cinetpay = provider == CINETPAY_PROVIDER_CODE
    required_setting_groups = (
        ("CINETPAY_APIKEY", ("CINETPAY_APIKEY", "CINETPAY_API_KEY", "JOATHAM_PAYMENT_SECRET_KEY")),
        ("CINETPAY_API_PASSWORD", ("CINETPAY_API_PASSWORD", "JOATHAM_PAYMENT_API_PASSWORD")),
        ("CINETPAY_CURRENCY", ("CINETPAY_CURRENCY", "JOATHAM_PAYMENT_CURRENCY")),
        ("JOATHAM_PAYMENT_CALLBACK_URL", ("JOATHAM_PAYMENT_CALLBACK_URL",)),
        ("JOATHAM_PAYMENT_RETURN_URL", ("JOATHAM_PAYMENT_RETURN_URL",)),
    )
    present_required_settings = []
    missing_required_settings = []
    for display_name, setting_names in required_setting_groups:
        present, _source = _payment_setting_presence(*setting_names)
        if present:
            present_required_settings.append(display_name)
        else:
            missing_required_settings.append(display_name)

    payment_url, payment_url_source = _payment_url_source("CINETPAY_PAYMENT_URL", CINETPAY_DEFAULT_PAYMENT_URL)
    check_url, check_url_source = _payment_url_source(
        "CINETPAY_PAYMENT_CHECK_URL",
        CINETPAY_DEFAULT_PAYMENT_CHECK_URL,
    )
    auth_url, auth_url_source = _payment_url_source("CINETPAY_AUTH_URL", CINETPAY_DEFAULT_AUTH_URL)
    sandbox_setting = getattr(settings, "JOATHAM_PAYMENT_SANDBOX", None)
    sandbox_flag = bool(sandbox_setting)
    payment_environment = _payment_environment_label(enabled, provider_is_cinetpay, sandbox_setting)
    payment_url_source_label = _payment_url_source_label(payment_url_source)
    check_url_source_label = _payment_url_source_label(check_url_source)
    auth_url_source_label = _payment_url_source_label(auth_url_source)
    configured = enabled and provider_is_cinetpay and not missing_required_settings

    optional_setting_groups = (
        ("CINETPAY_SITE_ID", ("CINETPAY_SITE_ID", "JOATHAM_PAYMENT_PUBLIC_KEY"), ""),
        ("CINETPAY_SECRET_KEY", ("CINETPAY_SECRET_KEY", "JOATHAM_PAYMENT_WEBHOOK_SECRET"), ""),
        ("CINETPAY_CHANNELS", ("CINETPAY_CHANNELS", "JOATHAM_PAYMENT_CHANNELS"), "MOBILE_MONEY"),
        ("CINETPAY_CHANNEL", ("CINETPAY_CHANNEL",), "PUSH"),
        ("CINETPAY_AUTH_URL", ("CINETPAY_AUTH_URL",), CINETPAY_DEFAULT_AUTH_URL),
        ("CINETPAY_PAYMENT_URL", ("CINETPAY_PAYMENT_URL",), CINETPAY_DEFAULT_PAYMENT_URL),
        ("CINETPAY_PAYMENT_CHECK_URL", ("CINETPAY_PAYMENT_CHECK_URL",), CINETPAY_DEFAULT_PAYMENT_CHECK_URL),
        (
            "CINETPAY_CHECKOUT_V2_PAYMENT_CHECK_URL",
            ("CINETPAY_CHECKOUT_V2_PAYMENT_CHECK_URL", "CINETPAY_LEGACY_PAYMENT_CHECK_URL"),
            CINETPAY_LEGACY_CHECKOUT_V2_PAYMENT_CHECK_URL,
        ),
        ("JOATHAM_PAYMENT_HTTP_TIMEOUT", ("JOATHAM_PAYMENT_HTTP_TIMEOUT",), ""),
        ("JOATHAM_PAYMENT_SANDBOX", ("JOATHAM_PAYMENT_SANDBOX",), ""),
    )
    optional_settings = []
    for display_name, setting_names, default in optional_setting_groups:
        present, source = _payment_setting_presence(*setting_names, default=default)
        optional_settings.append({"name": display_name, "present": present, "source": source})

    warnings = []
    if not enabled:
        warnings.append("Paiement automatique desactive.")
    if not provider:
        warnings.append("Provider de paiement non renseigne.")
    elif not provider_is_cinetpay:
        warnings.append("Provider actif different de CinetPay.")
    if provider_is_cinetpay and missing_required_settings:
        warnings.append("Configuration CinetPay incomplete.")
    if enabled and payment_environment == "Ambigu":
        warnings.append("Environnement CinetPay ambigu : vérifiez JOATHAM_PAYMENT_SANDBOX et le provider.")
    if enabled and provider_is_cinetpay and (auth_url_source == "default" or payment_url_source == "default" or check_url_source == "default"):
        warnings.append("URLs CinetPay par défaut utilisées ; confirmez leur environnement avant activation réelle.")
    custom_urls = (
        (auth_url, auth_url_source),
        (payment_url, payment_url_source),
        (check_url, check_url_source),
    )
    if provider_is_cinetpay and sandbox_setting not in (None, "") and sandbox_flag and any(
        source == "custom" and _url_looks_like_production(url) for url, source in custom_urls
    ):
        warnings.append("Mode sandbox actif avec URL CinetPay de production personnalisée.")
    if provider_is_cinetpay and sandbox_setting not in (None, "") and not sandbox_flag and any(
        source == "custom" and _url_looks_like_sandbox(url) for url, source in custom_urls
    ):
        warnings.append("Mode production actif avec URL CinetPay sandbox personnalisée.")

    return {
        "enabled": enabled,
        "provider": provider,
        "provider_is_cinetpay": provider_is_cinetpay,
        "configured": configured,
        "missing_required_settings": missing_required_settings,
        "present_required_settings": present_required_settings,
        "optional_settings": optional_settings,
        "payment_environment": payment_environment,
        "payment_url_source": payment_url_source,
        "check_url_source": check_url_source,
        "auth_url_source": auth_url_source,
        "payment_url_source_label": payment_url_source_label,
        "check_url_source_label": check_url_source_label,
        "auth_url_source_label": auth_url_source_label,
        "auth_url": _safe_diagnostic_url(auth_url),
        "payment_url": _safe_diagnostic_url(payment_url),
        "check_url": _safe_diagnostic_url(check_url),
        "sandbox_flag": sandbox_flag,
        "warnings": warnings,
    }
