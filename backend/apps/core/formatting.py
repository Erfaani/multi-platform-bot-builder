"""Localized formatting — the single place money and numbers become strings.

Ad-hoc formatting elsewhere is a review rejection (I18N.md §4).
"""

from __future__ import annotations

from decimal import Decimal

from django.core.cache import cache
from django.utils import translation

from apps.core.money import Money

CACHE_KEY = "currencies:v1"
CACHE_TTL = 300

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
PERSIAN_LOCALES = {"fa"}


def currency_registry() -> dict[str, dict]:
    """Currency metadata, cached. Falls back to an empty registry pre-migration."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    from apps.core.models import Currency

    try:
        registry = {
            row.code: {
                "code": row.code,
                "name": row.name,
                "symbol": row.symbol,
                "exponent": row.exponent,
                "display_unit": row.display_unit,
                "display_divisor": row.display_divisor,
            }
            for row in Currency.objects.filter(is_active=True)
        }
    except Exception:  # pragma: no cover - table absent before first migrate
        return {}

    cache.set(CACHE_KEY, registry, CACHE_TTL)
    return registry


def invalidate_currency_cache() -> None:
    cache.delete(CACHE_KEY)


def get_exponent(currency: str) -> int:
    entry = currency_registry().get(currency.upper())
    return entry["exponent"] if entry else 2


def to_persian_digits(text: str) -> str:
    return text.translate(PERSIAN_DIGITS)


def format_number(value: Decimal | int, *, locale: str | None = None, decimals: int = 0) -> str:
    locale = locale or translation.get_language() or "en"
    formatted = f"{value:,.{decimals}f}"
    if locale.split("-")[0] in PERSIAN_LOCALES:
        formatted = to_persian_digits(formatted).replace(",", "٬").replace(".", "٫")
    return formatted


def format_money(money: Money, *, locale: str | None = None) -> str:
    """Render an amount for display.

    Toman is handled here and only here: IRR is stored, and Persian output divides by
    the currency's ``display_divisor`` and labels the result — it is a presentation
    unit, not a currency (ADR-0004).
    """
    locale = locale or translation.get_language() or "en"
    base_locale = locale.split("-")[0]
    entry = currency_registry().get(money.currency, {})

    exponent = entry.get("exponent", 2)
    divisor = entry.get("display_divisor", 1) or 1
    display_unit = entry.get("display_unit", "")
    symbol = entry.get("symbol", "")

    value = money.to_major(exponent)
    use_display_unit = divisor > 1 and display_unit and base_locale in PERSIAN_LOCALES
    if use_display_unit:
        value = value / Decimal(divisor)
        decimals = 0
    else:
        decimals = exponent if exponent <= 2 else 2

    number = format_number(value, locale=locale, decimals=decimals)

    if use_display_unit:
        label = "تومان" if base_locale == "fa" else display_unit.title()
        return f"{number} {label}"
    if symbol and base_locale not in PERSIAN_LOCALES:
        return f"{symbol}{number}" if len(symbol) == 1 else f"{symbol} {number}"
    return f"{number} {money.currency}"


def money_to_representation(money: Money | None, *, locale: str | None = None) -> dict | None:
    """The API shape for money — never a bare number (API.md §1)."""
    if money is None:
        return None
    return {
        "amount_minor": money.amount_minor,
        "currency": money.currency,
        "formatted": format_money(money, locale=locale),
    }
