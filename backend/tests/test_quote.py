"""Quote building: validation, dependency expansion, and price snapshotting."""

from __future__ import annotations

import pytest

from apps.core.errors import ConflictError, NotFoundError, ValidationError
from apps.orders.models import Quote
from apps.orders.services import build_quote, claim_quote, get_quote_for_request
from apps.pricing.services import set_price

pytestmark = pytest.mark.django_db


def build(**kwargs):
    payload = {
        "template_slug": "clinic",
        "platforms": ["telegram"],
        "feature_slugs": [],
        "currency": "USD",
    }
    payload.update(kwargs)
    return build_quote(**payload)


class TestValidation:
    def test_unknown_template_is_rejected(self, catalogue):
        with pytest.raises(NotFoundError):
            build(template_slug="does-not-exist")

    def test_no_platform_is_rejected(self, catalogue):
        with pytest.raises(ValidationError):
            build(platforms=[])

    def test_unknown_platform_is_rejected(self, catalogue):
        with pytest.raises(ValidationError):
            build(platforms=["whatsapp"])

    def test_preview_cannot_be_purchased(self, catalogue):
        """`preview` is a rendering target, never a sellable channel."""
        with pytest.raises(ValidationError):
            build(platforms=["preview"])

    def test_unknown_feature_is_rejected(self, catalogue):
        with pytest.raises(ValidationError):
            build(feature_slugs=["teleportation"])

    def test_feature_outside_the_template_is_rejected(self, catalogue):
        """The clinic template does not offer table reservation."""
        with pytest.raises(ValidationError):
            build(feature_slugs=["table_reservation"])


class TestDependencies:
    def test_required_features_are_added_even_if_omitted(self, catalogue):
        quote, _ = build(feature_slugs=[])
        assert "business_profile" in quote.resolved_features

    def test_dependencies_are_pulled_in_and_reported(self, catalogue):
        """Picking the AI assistant must also enable FAQ, and say so."""
        quote, auto_added = build(feature_slugs=["ai_assistant"])

        assert "faq" in quote.resolved_features
        assert "faq" in auto_added

    def test_transitive_dependencies_are_resolved(self, catalogue):
        quote, _ = build(feature_slugs=["appointment_reminders"])
        # reminders → appointment → working_hours + business_profile
        for slug in ("appointment", "working_hours", "business_profile"):
            assert slug in quote.resolved_features

    def test_dependencies_come_before_their_dependents(self, catalogue):
        quote, _ = build(feature_slugs=["appointment_reminders"])
        resolved = quote.resolved_features
        assert resolved.index("appointment") < resolved.index("appointment_reminders")

    def test_selected_features_are_kept_separate_from_resolved(self, catalogue):
        quote, _ = build(feature_slugs=["ai_assistant"])
        assert quote.selected_features == ["ai_assistant"]
        assert len(quote.resolved_features) > 1


class TestPlatformAvailability:
    def test_a_feature_unavailable_on_a_platform_blocks_the_quote(self, catalogue):
        """Food ordering needs media groups, which Bale does not have (R-02).

        Refusing the sale is the point: taking money for something undeliverable is
        the failure mode this check exists to prevent.
        """
        with pytest.raises(ValidationError) as exc:
            build(
                template_slug="restaurant",
                platforms=["bale"],
                feature_slugs=["food_ordering"],
            )
        assert exc.value.code == "quote.feature_unavailable_on_platform"

    def test_the_same_feature_is_sellable_on_telegram(self, catalogue):
        quote, _ = build(
            template_slug="restaurant", platforms=["telegram"], feature_slugs=["food_ordering"]
        )
        assert "food_ordering" in quote.resolved_features

    def test_the_conflict_names_the_feature_and_platform(self, catalogue):
        with pytest.raises(ValidationError) as exc:
            build(
                template_slug="restaurant", platforms=["bale"], feature_slugs=["food_ordering"]
            )
        conflict = exc.value.details["conflicts"][0]
        assert conflict["feature"] == "food_ordering"
        assert conflict["platform"] == "bale"


class TestPricing:
    def test_the_quote_is_priced_server_side(self, catalogue):
        quote, _ = build(feature_slugs=["faq"])
        assert quote.total_minor > 0
        assert quote.items.exists()

    def test_totals_equal_the_sum_of_the_items(self, catalogue):
        quote, _ = build(platforms=["telegram", "bale"], feature_slugs=["appointment", "faq"])
        summed = sum(item.amount_minor for item in quote.items.all())
        assert quote.total_minor == summed

    def test_iranian_customers_are_priced_in_rials(self, catalogue):
        quote, _ = build(currency=None, country="IR")
        assert quote.currency == "IRR"

    def test_a_quote_carries_exactly_one_currency(self, catalogue):
        quote, _ = build(platforms=["telegram", "bale"], feature_slugs=["appointment"])
        assert {item.currency for item in quote.items.all()} == {quote.currency}

    def test_multi_platform_costs_less_than_two_single_bots(self, catalogue):
        telegram, _ = build(platforms=["telegram"])
        both, _ = build(platforms=["telegram", "bale"])
        assert both.total_minor < telegram.total_minor * 2

    def test_repricing_replaces_stale_lines(self, catalogue):
        quote, _ = build(feature_slugs=["faq"])
        assert quote.items.filter(feature_slug="faq").exists()

        quote, _ = build(feature_slugs=[], quote=quote)
        assert not quote.items.filter(feature_slug="faq").exists()


class TestSnapshotting:
    def test_a_later_price_change_does_not_alter_an_existing_quote(
        self, catalogue, usd_price_list
    ):
        """The core promise of spec §12."""
        quote, _ = build(feature_slugs=["faq"])
        original_total = quote.total_minor
        original_line = quote.items.get(price_key="feature.faq.setup").amount_minor

        set_price(
            price_list=usd_price_list,
            price_key="feature.faq.setup",
            amount_minor=original_line + 5000,
        )

        quote.refresh_from_db()
        assert quote.total_minor == original_total
        assert quote.items.get(price_key="feature.faq.setup").amount_minor == original_line

    def test_items_reference_the_version_that_priced_them(self, catalogue):
        quote, _ = build(feature_slugs=["faq"])
        item = quote.items.get(price_key="feature.faq.setup")
        assert item.price_version_id is not None
        assert item.price_version.amount_minor == item.unit_amount_minor

    def test_a_priced_version_cannot_be_deleted(self, catalogue):
        """Deleting it would rewrite what a customer was quoted."""
        from django.db.models import ProtectedError

        quote, _ = build(feature_slugs=["faq"])
        version = quote.items.get(price_key="feature.faq.setup").price_version

        with pytest.raises(ProtectedError):
            version.delete()


class TestOwnership:
    def test_an_anonymous_quote_needs_its_session_secret(self, catalogue):
        quote, _ = build()

        assert get_quote_for_request(
            public_id=str(quote.public_id), session_secret=quote.session_secret
        )

    def test_the_public_id_alone_is_not_enough(self, catalogue):
        """Otherwise a guessed or shared link would expose a business draft."""
        quote, _ = build()
        with pytest.raises(NotFoundError):
            get_quote_for_request(public_id=str(quote.public_id))

    def test_a_wrong_secret_is_refused(self, catalogue):
        quote, _ = build()
        with pytest.raises(NotFoundError):
            get_quote_for_request(public_id=str(quote.public_id), session_secret="nope")

    def test_claiming_binds_the_quote_to_a_tenant(self, catalogue, tenant_a, user):
        quote, _ = build()
        claimed = claim_quote(quote=quote, tenant=tenant_a, user=user)
        assert claimed.tenant_id == tenant_a.pk
        assert claimed.is_claimed

    def test_a_claimed_quote_is_unreachable_by_secret(self, catalogue, tenant_a, user):
        quote, _ = build()
        secret = quote.session_secret
        claim_quote(quote=quote, tenant=tenant_a, user=user)

        with pytest.raises(NotFoundError):
            get_quote_for_request(public_id=str(quote.public_id), session_secret=secret)

    def test_a_member_can_read_a_claimed_quote(self, catalogue, tenant_a, user):
        quote, _ = build()
        claim_quote(quote=quote, tenant=tenant_a, user=user)

        assert get_quote_for_request(public_id=str(quote.public_id), user=user)

    def test_another_tenant_cannot_read_it(self, catalogue, tenant_a, tenant_b, user, other_user):
        quote, _ = build()
        claim_quote(quote=quote, tenant=tenant_a, user=user)

        with pytest.raises(NotFoundError):
            get_quote_for_request(public_id=str(quote.public_id), user=other_user)

    def test_a_quote_cannot_be_claimed_twice(self, catalogue, tenant_a, tenant_b, user):
        quote, _ = build()
        claim_quote(quote=quote, tenant=tenant_a, user=user)

        with pytest.raises(ConflictError):
            claim_quote(quote=quote, tenant=tenant_b, user=user)

    def test_reclaiming_by_the_same_tenant_is_idempotent(self, catalogue, tenant_a, user):
        quote, _ = build()
        claim_quote(quote=quote, tenant=tenant_a, user=user)
        assert claim_quote(quote=quote, tenant=tenant_a, user=user).tenant_id == tenant_a.pk

    def test_an_expired_quote_cannot_be_claimed(self, catalogue, tenant_a, user):
        from datetime import timedelta

        from django.utils import timezone

        quote, _ = build()
        Quote.objects.filter(pk=quote.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        quote.refresh_from_db()

        with pytest.raises(ConflictError):
            claim_quote(quote=quote, tenant=tenant_a, user=user)
