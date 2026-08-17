"""The pricing calculator. Pure unit tests — no database.

This is the file that decides what customers are charged, so it is tested exhaustively
and without any infrastructure in the way.
"""

from __future__ import annotations

import pytest

from apps.pricing.domain import (
    PriceEntry,
    PriceNotFound,
    calculate_quote,
)

ONE_TIME = "ONE_TIME"
MONTHLY = "RECURRING_MONTHLY"


def prices(**overrides) -> dict[str, PriceEntry]:
    base = {
        "template.clinic.base": PriceEntry(19900, ONE_TIME, 1),
        "template.generic.base": PriceEntry(9900, ONE_TIME, 2),
        "platform.telegram.base": PriceEntry(4900, ONE_TIME, 3),
        "platform.bale.base": PriceEntry(4900, ONE_TIME, 4),
        "platform.multi.surcharge": PriceEntry(2900, ONE_TIME, 5),
        "feature.faq.setup": PriceEntry(1900, ONE_TIME, 6),
        "feature.appointment.setup": PriceEntry(5900, ONE_TIME, 7),
        "feature.appointment.monthly": PriceEntry(900, MONTHLY, 8),
        "feature.business_profile.setup": PriceEntry(0, ONE_TIME, 9),
        "hosting.standard.monthly": PriceEntry(1900, MONTHLY, 10),
    }
    base.update(overrides)
    return base


def quote(platforms, features=(), template="clinic", **kwargs):
    return calculate_quote(
        currency="USD",
        template_slug=template,
        platforms=list(platforms),
        feature_slugs=list(features),
        prices=kwargs.pop("prices", prices()),
        **kwargs,
    )


class TestPlatformPricing:
    def test_single_platform_charges_one_base(self):
        totals = quote(["telegram"])
        keys = [item.price_key for item in totals.items]
        assert "platform.telegram.base" in keys
        assert "platform.multi.surcharge" not in keys

    def test_two_platforms_do_not_double_the_price(self):
        """Spec §9: base + multi-platform fee, never base × 2."""
        single = quote(["telegram"]).subtotal
        both = quote(["telegram", "bale"]).subtotal

        assert both > single
        assert both.amount_minor < single.amount_minor * 2

    def test_two_platforms_add_exactly_the_surcharge(self):
        single = quote(["telegram"]).subtotal
        both = quote(["telegram", "bale"]).subtotal
        assert both.amount_minor - single.amount_minor == 2900

    def test_template_base_is_charged_once_regardless_of_platforms(self):
        """Shared business configuration is built once, so it is billed once."""
        items = quote(["telegram", "bale"]).items
        template_lines = [i for i in items if i.price_key.startswith("template.")]
        assert len(template_lines) == 1
        assert template_lines[0].quantity == 1

    def test_primary_platform_is_the_more_expensive_one(self):
        """Otherwise the total would depend on tick-box order."""
        custom = prices(**{"platform.bale.base": PriceEntry(7900, ONE_TIME, 4)})
        totals = quote(["telegram", "bale"], prices=custom)
        keys = [item.price_key for item in totals.items]
        assert "platform.bale.base" in keys
        assert "platform.telegram.base" not in keys

    def test_platform_order_does_not_change_the_total(self):
        assert quote(["telegram", "bale"]).subtotal == quote(["bale", "telegram"]).subtotal

    def test_duplicate_platforms_are_collapsed(self):
        assert quote(["telegram", "telegram"]).subtotal == quote(["telegram"]).subtotal

    def test_no_platform_is_rejected(self):
        with pytest.raises(ValueError):
            quote([])


class TestFeaturePricing:
    def test_features_are_charged_once_not_per_platform(self):
        """Spec §61.1: one configuration drives both channels."""
        one = quote(["telegram"], ["faq"])
        both = quote(["telegram", "bale"], ["faq"])

        faq_one = [i for i in one.items if i.feature_slug == "faq"]
        faq_both = [i for i in both.items if i.feature_slug == "faq"]
        assert len(faq_one) == len(faq_both) == 1
        assert faq_one[0].amount == faq_both[0].amount

    def test_setup_and_monthly_are_separate_lines(self):
        items = quote(["telegram"], ["appointment"]).items
        kinds = {i.price_key: i.billing_kind for i in items if i.feature_slug == "appointment"}
        assert kinds["feature.appointment.setup"] == ONE_TIME
        assert kinds["feature.appointment.monthly"] == MONTHLY

    def test_free_features_do_not_clutter_the_quote(self):
        items = quote(["telegram"], ["business_profile"]).items
        assert not [i for i in items if i.feature_slug == "business_profile"]

    def test_feature_without_a_monthly_price_gets_only_setup(self):
        items = quote(["telegram"], ["faq"]).items
        assert [i.price_key for i in items if i.feature_slug == "faq"] == ["feature.faq.setup"]


class TestTotals:
    def test_one_time_and_recurring_are_separated(self):
        totals = quote(["telegram"], ["appointment"])
        assert totals.recurring_monthly.amount_minor == 900 + 1900  # feature + hosting
        assert totals.one_time.amount_minor > 0

    def test_subtotal_is_setup_plus_first_period(self):
        totals = quote(["telegram"], ["appointment"])
        assert totals.subtotal == totals.one_time + totals.recurring_monthly

    def test_totals_equal_the_sum_of_the_lines(self):
        totals = quote(["telegram", "bale"], ["faq", "appointment"])
        summed = sum(item.amount.amount_minor for item in totals.items)
        assert totals.subtotal.amount_minor == summed

    def test_hosting_can_be_excluded(self):
        totals = calculate_quote(
            currency="USD",
            template_slug="clinic",
            platforms=["telegram"],
            feature_slugs=[],
            prices=prices(),
            include_hosting=False,
        )
        assert "hosting.standard.monthly" not in [i.price_key for i in totals.items]

    def test_every_line_carries_the_quote_currency(self):
        totals = quote(["telegram", "bale"], ["appointment"])
        assert {item.amount.currency for item in totals.items} == {"USD"}


class TestMissingPrices:
    def test_missing_template_price_refuses_to_quote(self):
        """Quoting from an incomplete price list would silently under-charge."""
        incomplete = prices()
        del incomplete["template.clinic.base"]
        with pytest.raises(PriceNotFound):
            quote(["telegram"], prices=incomplete)

    def test_missing_platform_price_refuses_to_quote(self):
        incomplete = prices()
        del incomplete["platform.bale.base"]
        with pytest.raises(PriceNotFound):
            quote(["telegram", "bale"], prices=incomplete)

    def test_missing_surcharge_refuses_multi_platform(self):
        incomplete = prices()
        del incomplete["platform.multi.surcharge"]
        with pytest.raises(PriceNotFound):
            quote(["telegram", "bale"], prices=incomplete)

    def test_missing_optional_feature_price_is_tolerated(self):
        """A feature with no price row is free, not an error."""
        incomplete = prices()
        del incomplete["feature.faq.setup"]
        totals = quote(["telegram"], ["faq"], prices=incomplete)
        assert not [i for i in totals.items if i.feature_slug == "faq"]
