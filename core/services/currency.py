from decimal import Decimal, InvalidOperation

from core.services.world import get_currency_name, get_currency_symbol


def get_currency_code(entreprise, default="CDF"):
    if entreprise is None:
        return default
    return (getattr(entreprise, "devise", None) or default).strip().upper()


def get_currency_label(currency_code):
    return get_currency_name((currency_code or "CDF").upper())


def get_currency_wording(currency_code):
    return get_currency_name((currency_code or "CDF").upper()).lower()


def get_currency_display(currency_code):
    currency_code = (currency_code or "CDF").upper()
    return f"{currency_code} / {get_currency_label(currency_code)}"


def format_decimal_number(value):
    try:
        amount = Decimal(value or 0).quantize(Decimal("1.00"))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0.00")
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")


def format_currency_amount(value, currency_code="CDF"):
    currency_code = (currency_code or "CDF").upper()
    return f"{format_decimal_number(value)} {currency_code}"


def format_amount_for_entreprise(value, entreprise):
    return format_currency_amount(value, get_currency_code(entreprise))


def get_currency_symbol_for_entreprise(entreprise):
    return get_currency_symbol(get_currency_code(entreprise))
