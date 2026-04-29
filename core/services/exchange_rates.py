import logging
import os
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import requests

from django.utils import timezone

from core.models import ExchangeRate, PlatformSettings


logger = logging.getLogger(__name__)


class ExchangeRateUnavailable(ValueError):
    pass


@dataclass
class ConversionResult:
    amount: Decimal
    source_currency: str
    target_currency: str
    rate: Decimal
    provider: str
    rate_date: object = None
    fetched_at: object = None
    unavailable: bool = False
    message: str = ""


def normalize_currency_code(code):
    return (code or "").strip().upper()


def get_platform_currency():
    return normalize_currency_code(PlatformSettings.get_solo().devise_plateforme or "USD") or "USD"


def get_company_currency(entreprise):
    company_currency = normalize_currency_code(getattr(entreprise, "devise", ""))
    if company_currency:
        return company_currency
    return normalize_currency_code(PlatformSettings.get_solo().devise_defaut or get_platform_currency())


def _cache_cutoff():
    settings = PlatformSettings.get_solo()
    return timezone.now() - timedelta(hours=settings.exchange_rate_cache_hours or 12)


def _latest_rate(source_currency, target_currency, *, recent_only=False):
    queryset = ExchangeRate.objects.filter(
        devise_source=source_currency,
        devise_cible=target_currency,
        actif=True,
    )
    if recent_only:
        queryset = queryset.filter(fetched_at__gte=_cache_cutoff())
    return queryset.order_by("-date_taux", "-fetched_at", "-id").first()


def _provider_settings():
    settings = PlatformSettings.get_solo()
    provider = os.getenv("EXCHANGE_RATE_PROVIDER") or settings.exchange_rate_provider or "exchangerate_api"
    api_key = os.getenv("EXCHANGE_RATE_API_KEY") or settings.exchange_rate_api_key or ""
    return provider.strip(), api_key.strip()


def _fetch_exchangerate_api_rate(source_currency, target_currency, api_key):
    url = f"https://open.er-api.com/v6/latest/{source_currency}"
    logger.info("Calling exchange rate provider URL: %s", url)
    try:
        response = requests.get(url, timeout=5)
    except requests.RequestException as exc:
        logger.warning("Exchange rate provider request failed url=%s error=%s", url, exc)
        raise ExchangeRateUnavailable("Provider taux de change indisponible.") from exc

    logger.info("Exchange rate provider response url=%s status_code=%s", url, response.status_code)
    if response.status_code != 200:
        logger.warning(
            "Exchange rate provider non-200 response url=%s status_code=%s body=%s",
            url,
            response.status_code,
            response.text[:300],
        )
        raise ExchangeRateUnavailable(f"Provider taux de change indisponible. Status HTTP {response.status_code}.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ExchangeRateUnavailable("Reponse taux de change invalide.") from exc

    if payload.get("result") != "success":
        logger.warning("Exchange rate provider returned error url=%s payload=%s", url, payload)
        raise ExchangeRateUnavailable("Provider taux de change indisponible.")

    rates = payload.get("rates") or {}
    if target_currency not in rates:
        logger.warning("Exchange rate missing target currency url=%s target=%s", url, target_currency)
        raise ExchangeRateUnavailable(f"Taux {source_currency}->{target_currency} indisponible.")

    try:
        rate = Decimal(str(rates[target_currency]))
    except (KeyError, InvalidOperation) as exc:
        raise ExchangeRateUnavailable("Taux de change invalide.") from exc
    return rate, payload


def _fetch_rate_from_provider(source_currency, target_currency):
    provider, api_key = _provider_settings()
    if provider != "exchangerate_api":
        raise ExchangeRateUnavailable("Provider taux de change non supporte.")
    try:
        rate, payload = _fetch_exchangerate_api_rate(source_currency, target_currency, api_key)
    except ExchangeRateUnavailable as exc:
        logger.warning("Exchange rate provider failed source=%s target=%s error=%s", source_currency, target_currency, exc)
        raise ExchangeRateUnavailable("Conversion temporairement indisponible.") from exc
    now = timezone.now()
    return ExchangeRate.objects.create(
        devise_source=source_currency,
        devise_cible=target_currency,
        taux=rate,
        source_provider=provider,
        date_taux=now,
        metadata={"provider_payload": payload},
    )


def get_exchange_rate(source_currency, target_currency):
    source_currency = normalize_currency_code(source_currency)
    target_currency = normalize_currency_code(target_currency)
    if not source_currency or not target_currency:
        raise ExchangeRateUnavailable("Devise invalide.")
    if source_currency == target_currency:
        now = timezone.now()
        return ConversionResult(
            amount=Decimal("1"),
            source_currency=source_currency,
            target_currency=target_currency,
            rate=Decimal("1"),
            provider="identity",
            rate_date=now,
            fetched_at=now,
        )

    recent_rate = _latest_rate(source_currency, target_currency, recent_only=True)
    if recent_rate is not None:
        return ConversionResult(
            amount=recent_rate.taux,
            source_currency=source_currency,
            target_currency=target_currency,
            rate=recent_rate.taux,
            provider=recent_rate.source_provider,
            rate_date=recent_rate.date_taux,
            fetched_at=recent_rate.fetched_at,
        )

    try:
        fetched_rate = _fetch_rate_from_provider(source_currency, target_currency)
        return ConversionResult(
            amount=fetched_rate.taux,
            source_currency=source_currency,
            target_currency=target_currency,
            rate=fetched_rate.taux,
            provider=fetched_rate.source_provider,
            rate_date=fetched_rate.date_taux,
            fetched_at=fetched_rate.fetched_at,
        )
    except ExchangeRateUnavailable:
        fallback = _latest_rate(source_currency, target_currency)
        if fallback is not None:
            return ConversionResult(
                amount=fallback.taux,
                source_currency=source_currency,
                target_currency=target_currency,
                rate=fallback.taux,
                provider=f"{fallback.source_provider}_fallback",
                rate_date=fallback.date_taux,
                fetched_at=fallback.fetched_at,
            )
        raise


def convert_amount(amount, source_currency, target_currency):
    amount = Decimal(str(amount or "0")).quantize(Decimal("0.01"))
    rate_result = get_exchange_rate(source_currency, target_currency)
    converted = (amount * rate_result.rate).quantize(Decimal("0.01"))
    return ConversionResult(
        amount=converted,
        source_currency=rate_result.source_currency,
        target_currency=rate_result.target_currency,
        rate=rate_result.rate,
        provider=rate_result.provider,
        rate_date=rate_result.rate_date,
        fetched_at=rate_result.fetched_at,
    )


def get_plan_price_for_company(plan, entreprise):
    platform_currency = get_platform_currency()
    company_currency = get_company_currency(entreprise)
    official_amount = Decimal(str(getattr(plan, "prix", 0) or 0)).quantize(Decimal("0.01"))
    try:
        converted = convert_amount(official_amount, platform_currency, company_currency)
    except ExchangeRateUnavailable as exc:
        return {
            "official_amount": official_amount,
            "official_currency": platform_currency,
            "company_currency": company_currency,
            "estimated_amount": None,
            "rate": None,
            "rate_provider": "",
            "rate_date": None,
            "unavailable": True,
            "message": str(exc),
        }
    return {
        "official_amount": official_amount,
        "official_currency": platform_currency,
        "company_currency": company_currency,
        "estimated_amount": converted.amount,
        "rate": converted.rate,
        "rate_provider": converted.provider,
        "rate_date": converted.rate_date,
        "unavailable": False,
        "message": "",
    }
