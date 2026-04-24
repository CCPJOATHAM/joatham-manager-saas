from decimal import Decimal, ROUND_HALF_UP


DEFAULT_EXCHANGE_SOURCE = "manuel"
USD_CURRENCY = "USD"
DEFAULT_CURRENCY_LABELS = {
    "USD": "Dollar americain",
    "CDF": "Franc congolais",
    "EUR": "Euro",
    "XAF": "Franc CFA",
}
MANUAL_EXCHANGE_RATES = {
    "CDF": Decimal("2850.00"),
    "EUR": Decimal("0.92"),
    "XAF": Decimal("605.00"),
}


def _normalize_currency_code(currency_code):
    return (currency_code or USD_CURRENCY).strip().upper()


def get_currency_code(entreprise=None):
    if entreprise is None:
        return USD_CURRENCY
    return _normalize_currency_code(getattr(entreprise, "devise", ""))


def get_currency_label(currency_code):
    normalized_currency = _normalize_currency_code(currency_code)
    return DEFAULT_CURRENCY_LABELS.get(normalized_currency, normalized_currency)


def get_currency_wording(currency_code):
    return get_currency_label(currency_code)


def get_currency_display(entreprise=None):
    currency_code = get_currency_code(entreprise)
    return f"{currency_code} - {get_currency_label(currency_code)}"


def format_decimal_number(value, decimal_places=2):
    quantize_pattern = "0." + ("0" * max(int(decimal_places), 0))
    quantized_value = Decimal(value or 0).quantize(Decimal(quantize_pattern), rounding=ROUND_HALF_UP)
    return f"{quantized_value:,.{max(int(decimal_places), 0)}f}".replace(",", " ")


def format_amount_for_entreprise(amount, entreprise=None):
    return format_decimal_number(amount, decimal_places=2)


def get_manual_exchange_rate(currency_code):
    normalized_currency = _normalize_currency_code(currency_code)
    if normalized_currency == USD_CURRENCY:
        return Decimal("1.0000")
    return MANUAL_EXCHANGE_RATES.get(normalized_currency, Decimal("1.0000"))


def estimate_local_amount_from_usd(amount_usd, currency_code):
    normalized_currency = _normalize_currency_code(currency_code)
    exchange_rate = get_manual_exchange_rate(normalized_currency)
    estimated_amount = (Decimal(amount_usd) * exchange_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "currency_code": normalized_currency,
        "exchange_rate": exchange_rate,
        "estimated_amount": estimated_amount,
        "source": DEFAULT_EXCHANGE_SOURCE,
    }
