"""Buying more features for a bot that is already live (spec §24).

`provisioned_bot` starts with business_profile + contact + faq. These tests add
`location`, a feature the clinic template offers but this bot has not bought yet.
"""

from __future__ import annotations

import pytest

from apps.bots.models import BotFeature
from apps.core.errors import ConflictError, ValidationError
from apps.orders.domain.state_machine import Actor, OrderStatus
from apps.orders.models import Order, OrderKind
from apps.orders.services import build_addon_quote, place_order, transition_order
from apps.provisioning.saga import create_job, run_job

pytestmark = pytest.mark.django_db


def _pay(order: Order, user) -> Order:
    for target in (OrderStatus.RECEIPT_SUBMITTED, OrderStatus.PAYMENT_REVIEW, OrderStatus.PAID):
        actor = Actor.CUSTOMER if target == OrderStatus.RECEIPT_SUBMITTED else Actor.STAFF
        transition_order(order=order, target=target, actor_type=actor, user=user, scopes={"*"})
    order.refresh_from_db()
    return order


class TestBuildAddonQuote:
    def test_prices_only_the_new_feature(self, provisioned_bot, user):
        quote, auto_added = build_addon_quote(
            bot=provisioned_bot, feature_slugs=["location"], user=user
        )
        assert quote.resolved_features == ["location"]
        assert auto_added == []
        # No template/platform/hosting line — only the feature itself.
        assert quote.items.count() == 1
        assert quote.items.get().feature_slug == "location"
        assert quote.total_minor > 0

    def test_the_quote_is_pre_claimed_to_the_bots_tenant(self, provisioned_bot, user):
        quote, _ = build_addon_quote(bot=provisioned_bot, feature_slugs=["location"], user=user)
        assert quote.tenant_id == provisioned_bot.tenant_id
        assert quote.target_bot_id == provisioned_bot.pk

    def test_a_feature_already_enabled_is_rejected(self, provisioned_bot, user):
        with pytest.raises(ConflictError):
            build_addon_quote(bot=provisioned_bot, feature_slugs=["faq"], user=user)

    def test_an_unknown_feature_is_rejected(self, provisioned_bot, user):
        with pytest.raises(ValidationError):
            build_addon_quote(bot=provisioned_bot, feature_slugs=["not_a_real_feature"], user=user)

    def test_a_feature_not_offered_by_the_bots_template_is_rejected(self, provisioned_bot, user):
        with pytest.raises(ValidationError):
            build_addon_quote(bot=provisioned_bot, feature_slugs=["product_catalog"], user=user)


class TestPlaceAddonOrder:
    def test_placing_an_addon_quote_produces_an_addon_order(self, provisioned_bot, user):
        quote, _ = build_addon_quote(bot=provisioned_bot, feature_slugs=["location"], user=user)
        order = place_order(quote=quote, tenant=provisioned_bot.tenant, user=user)

        assert order.kind == OrderKind.ADDON
        assert order.target_bot_id == provisioned_bot.pk


class TestAddonProvisioning:
    def test_the_saga_only_runs_four_steps(self, provisioned_bot, user, fake_transport):
        quote, _ = build_addon_quote(bot=provisioned_bot, feature_slugs=["location"], user=user)
        order = _pay(place_order(quote=quote, tenant=provisioned_bot.tenant, user=user), user)

        job = create_job(order=order)
        assert job.steps.count() == 4

    def test_a_paid_addon_order_enables_the_feature(self, provisioned_bot, user, fake_transport):
        quote, _ = build_addon_quote(bot=provisioned_bot, feature_slugs=["location"], user=user)
        order = _pay(place_order(quote=quote, tenant=provisioned_bot.tenant, user=user), user)

        job = run_job(create_job(order=order))

        assert job.status == "SUCCEEDED"
        assert BotFeature.objects.filter(
            bot=provisioned_bot, feature__slug="location", is_enabled=True
        ).exists()

    def test_it_never_touches_the_credential_or_webhook(self, provisioned_bot, user, fake_transport):
        """The whole point of an add-on: nothing about the live channel is re-provisioned."""
        # provisioned_bot's own setup already called these; only calls made *during the
        # add-on run* are what this test cares about.
        fake_transport.calls.clear()

        quote, _ = build_addon_quote(bot=provisioned_bot, feature_slugs=["location"], user=user)
        order = _pay(place_order(quote=quote, tenant=provisioned_bot.tenant, user=user), user)

        run_job(create_job(order=order))

        assert not fake_transport.called("setWebhook")
        assert not fake_transport.called("getMe")

    def test_it_does_not_disturb_the_bots_existing_instance(self, provisioned_bot, user, fake_transport):
        instance_before = provisioned_bot.instances.get(platform="telegram")
        webhook_before = instance_before.webhook_url

        quote, _ = build_addon_quote(bot=provisioned_bot, feature_slugs=["location"], user=user)
        order = _pay(place_order(quote=quote, tenant=provisioned_bot.tenant, user=user), user)
        run_job(create_job(order=order))

        instance_before.refresh_from_db()
        assert instance_before.webhook_url == webhook_before

    def test_the_order_reaches_active(self, provisioned_bot, user, fake_transport):
        quote, _ = build_addon_quote(bot=provisioned_bot, feature_slugs=["location"], user=user)
        order = _pay(place_order(quote=quote, tenant=provisioned_bot.tenant, user=user), user)
        run_job(create_job(order=order))

        order.refresh_from_db()
        assert order.status == OrderStatus.ACTIVE.value

    def test_the_new_feature_bumps_the_runtime_cache(self, provisioned_bot, user, fake_transport):
        before = provisioned_bot.configuration.version

        quote, _ = build_addon_quote(bot=provisioned_bot, feature_slugs=["location"], user=user)
        order = _pay(place_order(quote=quote, tenant=provisioned_bot.tenant, user=user), user)
        run_job(create_job(order=order))

        provisioned_bot.configuration.refresh_from_db()
        assert provisioned_bot.configuration.version > before


class TestAddonQuoteApi:
    def test_available_features_excludes_what_the_bot_already_has(self, auth_client, provisioned_bot):
        response = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/available-features/")
        assert response.status_code == 200
        slugs = {row["slug"] for row in response.json()}
        assert "faq" not in slugs
        assert "location" in slugs

    def test_requesting_a_quote_returns_a_placeable_order(self, auth_client, provisioned_bot):
        response = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/addon-quotes/",
            {"features": ["location"]},
            format="json",
        )
        assert response.status_code == 201
        body = response.json()
        assert body["id"]
        assert body["auto_added_features"] == []

    def test_a_stranger_cannot_price_addons_for_another_tenants_bot(self, other_client, provisioned_bot):
        response = other_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/addon-quotes/",
            {"features": ["location"]},
            format="json",
        )
        assert response.status_code == 404
