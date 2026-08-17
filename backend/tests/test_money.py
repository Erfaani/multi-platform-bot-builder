"""Money arithmetic. Pure unit tests — no database, no Django settings needed."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.money import CurrencyMismatch, Money, sum_money


class TestConstruction:
    def test_rejects_float_amount(self):
        # The single most expensive mistake in a billing system.
        with pytest.raises(TypeError):
            Money(14.99, "USD")

    def test_rejects_bool_amount(self):
        with pytest.raises(TypeError):
            Money(True, "USD")

    def test_normalises_currency_case(self):
        assert Money(100, "usd").currency == "USD"

    def test_rejects_empty_currency(self):
        with pytest.raises(ValueError):
            Money(100, "")

    def test_from_major_usd(self):
        assert Money.from_major("149.00", "USD", exponent=2).amount_minor == 14_900

    def test_from_major_irr_has_no_minor_units(self):
        assert Money.from_major("49000000", "IRR", exponent=0).amount_minor == 49_000_000

    def test_from_major_usdt_six_decimals(self):
        assert Money.from_major("1.5", "USDT", exponent=6).amount_minor == 1_500_000

    def test_from_major_refuses_float(self):
        with pytest.raises(TypeError):
            Money.from_major(149.0, "USD", exponent=2)

    def test_to_major_round_trips(self):
        assert Money(14_900, "USD").to_major(2) == Decimal("149.00")


class TestArithmetic:
    def test_add(self):
        assert (Money(100, "USD") + Money(250, "USD")).amount_minor == 350

    def test_subtract(self):
        assert (Money(500, "USD") - Money(150, "USD")).amount_minor == 350

    def test_multiply_by_quantity(self):
        assert (Money(1_000, "USD") * 3).amount_minor == 3_000

    def test_multiply_rejects_non_integer(self):
        with pytest.raises(TypeError):
            Money(1_000, "USD") * 1.5

    def test_mixing_currencies_is_refused(self):
        # One order carries exactly one currency (spec §13).
        with pytest.raises(CurrencyMismatch):
            Money(100, "USD") + Money(100, "EUR")

    def test_comparison_across_currencies_is_refused(self):
        with pytest.raises(CurrencyMismatch):
            _ = Money(100, "USD") < Money(100, "EUR")

    def test_sum_of_empty_list_is_typed_zero(self):
        assert sum_money([], "IRR") == Money(0, "IRR")

    def test_totals_equal_the_sum_of_their_lines(self):
        lines = [Money(1_999, "USD"), Money(4_950, "USD"), Money(7_951, "USD")]
        assert sum_money(lines, "USD").amount_minor == 14_900


class TestRounding:
    def test_discount_uses_bankers_rounding(self):
        # 12345 * 0.085 = 1049.325 → 1049
        assert Money(12_345, "USD").apply_rate("0.085").amount_minor == 1_049

    def test_half_to_even_rounds_down_on_a_tie(self):
        # 250 * 0.01 = 2.5 → 2 (nearest even), not 3
        assert Money(250, "USD").apply_rate("0.01").amount_minor == 2

    def test_half_to_even_rounds_up_on_a_tie(self):
        # 750 * 0.01 = 7.5 → 8 (nearest even)
        assert Money(750, "USD").apply_rate("0.01").amount_minor == 8


class TestValueSemantics:
    def test_money_is_immutable(self):
        with pytest.raises(Exception):
            Money(100, "USD").amount_minor = 200

    def test_equality_is_by_value(self):
        assert Money(100, "USD") == Money(100, "USD")
        assert Money(100, "USD") != Money(100, "EUR")

    def test_negative_amounts_are_allowed_for_adjustments(self):
        assert Money(-500, "USD").is_negative
