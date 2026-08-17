"""Price immutability and snapshotting (spec §12).

"If a feature costs $10 today and $15 tomorrow, old orders must still show $10" is the
requirement. These tests check it is a property of the schema, not of anyone's diligence.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.pricing.models import BillingKind, PriceVersion
from apps.pricing.services import live_prices, price_history, resolve_price_list, set_price

pytestmark = pytest.mark.django_db

KEY = "feature.test_widget.setup"


class TestPriceChanges:
    def test_changing_a_price_closes_the_old_version(self, usd_price_list):
        first = set_price(price_list=usd_price_list, price_key=KEY, amount_minor=1000)
        second = set_price(price_list=usd_price_list, price_key=KEY, amount_minor=1500)

        first.refresh_from_db()
        assert first.valid_to is not None, "the superseded price must be closed"
        assert second.valid_to is None
        assert first.pk != second.pk

    def test_the_old_amount_is_never_overwritten(self, usd_price_list):
        first = set_price(price_list=usd_price_list, price_key=KEY, amount_minor=1000)
        set_price(price_list=usd_price_list, price_key=KEY, amount_minor=1500)

        first.refresh_from_db()
        assert first.amount_minor == 1000

    def test_history_is_preserved_in_order(self, usd_price_list):
        for amount in (1000, 1500, 2000):
            set_price(price_list=usd_price_list, price_key=KEY, amount_minor=amount)

        history = price_history(usd_price_list, KEY)
        assert [row.amount_minor for row in history] == [2000, 1500, 1000]

    def test_setting_the_same_price_is_a_no_op(self, usd_price_list):
        """Re-seeding must not churn history."""
        first = set_price(price_list=usd_price_list, price_key=KEY, amount_minor=1000)
        second = set_price(price_list=usd_price_list, price_key=KEY, amount_minor=1000)

        assert first.pk == second.pk
        assert PriceVersion.objects.filter(price_list=usd_price_list, price_key=KEY).count() == 1

    def test_changing_only_the_billing_kind_creates_a_version(self, usd_price_list):
        set_price(price_list=usd_price_list, price_key=KEY, amount_minor=1000)
        set_price(
            price_list=usd_price_list,
            price_key=KEY,
            amount_minor=1000,
            billing_kind=BillingKind.RECURRING_MONTHLY,
        )
        assert PriceVersion.objects.filter(price_list=usd_price_list, price_key=KEY).count() == 2

    def test_negative_prices_are_rejected(self, usd_price_list):
        from apps.core.errors import ValidationError

        with pytest.raises(ValidationError):
            set_price(price_list=usd_price_list, price_key=KEY, amount_minor=-100)


class TestLivePriceConstraint:
    def test_two_live_prices_for_one_key_are_impossible(self, usd_price_list):
        """Two live rows would make the total depend on row ordering."""
        set_price(price_list=usd_price_list, price_key=KEY, amount_minor=1000)

        with pytest.raises(IntegrityError), transaction.atomic():
            PriceVersion.objects.create(
                price_list=usd_price_list, price_key=KEY, amount_minor=1234
            )

    def test_closed_versions_may_coexist(self, usd_price_list):
        for amount in (1000, 1500, 2000):
            set_price(price_list=usd_price_list, price_key=KEY, amount_minor=amount)

        rows = PriceVersion.objects.filter(price_list=usd_price_list, price_key=KEY)
        assert rows.count() == 3
        assert rows.live().count() == 1

    def test_live_prices_returns_only_current_amounts(self, usd_price_list):
        set_price(price_list=usd_price_list, price_key=KEY, amount_minor=1000)
        set_price(price_list=usd_price_list, price_key=KEY, amount_minor=1500)

        assert live_prices(usd_price_list)[KEY].amount_minor == 1500


class TestPriceListResolution:
    def test_currency_selects_the_list(self, catalogue):
        assert resolve_price_list(currency="IRR").currency == "IRR"
        assert resolve_price_list(currency="USD").currency == "USD"

    def test_country_selects_the_scoped_list(self, catalogue):
        assert resolve_price_list(country="IR").currency == "IRR"

    def test_unknown_country_falls_back_to_the_default_list(self, catalogue):
        assert resolve_price_list(country="DE").is_default

    def test_unsold_currency_is_refused(self, catalogue):
        from apps.core.errors import NotFoundError

        with pytest.raises(NotFoundError):
            resolve_price_list(currency="JPY")

    def test_currency_wins_over_country(self, catalogue):
        """An Iranian customer paying in USD gets the USD list, not the IRR one."""
        assert resolve_price_list(currency="USD", country="IR").currency == "USD"
