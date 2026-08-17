"""Localized formatting, including the Toman rule (ADR-0004).

Toman is a *display unit* of IRR, not a currency. Getting it wrong is a 10x billing
error in either direction, so it gets its own tests.
"""

from __future__ import annotations

import pytest

from apps.core.formatting import format_money, format_number, to_persian_digits
from apps.core.money import Money

pytestmark = pytest.mark.django_db


class TestToman:
    def test_irr_displays_as_toman_in_persian(self, currencies):
        # 49,000,000 IRR is 4,900,000 Toman.
        result = format_money(Money(49_000_000, "IRR"), locale="fa")
        assert "تومان" in result
        assert to_persian_digits("4") in result

    def test_toman_divides_by_ten(self, currencies):
        formatted = format_money(Money(49_000_000, "IRR"), locale="fa")
        digits = "".join(ch for ch in formatted if ch in "۰۱۲۳۴۵۶۷۸۹")
        assert digits == to_persian_digits("4900000")

    def test_english_shows_rial_not_toman(self, currencies):
        # Toman is a Persian presentation convention; English keeps the real currency.
        result = format_money(Money(49_000_000, "IRR"), locale="en")
        assert "تومان" not in result
        assert "49,000,000" in result

    def test_storage_is_untouched_by_display(self, currencies):
        money = Money(49_000_000, "IRR")
        format_money(money, locale="fa")
        assert money.amount_minor == 49_000_000


class TestCurrencyFormatting:
    def test_usd_uses_two_decimals_and_symbol(self, currencies):
        assert format_money(Money(14_900, "USD"), locale="en") == "$149.00"

    def test_usdt_six_decimal_exponent(self, currencies):
        # 149_000_000 minor units at exponent 6 = 149.00
        assert "149.00" in format_money(Money(149_000_000, "USDT"), locale="en")

    def test_unknown_currency_falls_back_safely(self, currencies):
        result = format_money(Money(1_000, "GBP"), locale="en")
        assert "GBP" in result


class TestNumbers:
    def test_persian_digits_and_separators(self):
        result = format_number(1234567, locale="fa")
        assert "۱" in result and "٬" in result
        assert "1" not in result

    def test_english_digits(self):
        assert format_number(1234567, locale="en") == "1,234,567"
