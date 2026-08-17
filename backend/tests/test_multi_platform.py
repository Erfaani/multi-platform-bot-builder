"""Telegram + Bale on one bot (spec §3, BALE.md §5).

The promise is that a customer configures their business once and both channels serve it.
These tests hold that to account: one bot, one configuration, one set of business data,
two instances.
"""

from __future__ import annotations

import pytest

from apps.bots.credentials import add_pool_entry
from apps.bots.models import Bot, BotPlatformInstance, BotStatus
from apps.orders.domain.state_machine import Actor, OrderStatus
from apps.orders.services import build_quote, claim_quote, place_order, transition_order
from apps.provisioning.models import JobStatus
from apps.provisioning.saga import create_job, run_job

pytestmark = pytest.mark.django_db

BUSINESS = {
    "name": "Tehran Smile Clinic",
    "description": "A friendly dental clinic.",
    "phone": "+98 21 1234 5678",
    "email": "hello@clinic.example",
}


@pytest.fixture
def dual_pool(db, fake_transport):
    """One available bot on each channel."""
    add_pool_entry(
        platform="telegram",
        username="dual_clinic_tg_bot",
        token="7100000001:AA-telegram-pool-token-aaaaaaaaaaaa",
    )
    add_pool_entry(
        platform="bale",
        username="dual_clinic_bale_bot",
        token="7200000001:AA-bale-pool-token-bbbbbbbbbbbbbb",
    )


@pytest.fixture
def dual_order(catalogue, tenant_a, user, db):
    quote, _ = build_quote(
        template_slug="clinic",
        platforms=["telegram", "bale"],
        feature_slugs=["faq", "contact"],
        currency="USD",
        business_draft=BUSINESS,
    )
    claim_quote(quote=quote, tenant=tenant_a, user=user)
    order = place_order(quote=quote, tenant=tenant_a, user=user)

    for target, actor in (
        (OrderStatus.RECEIPT_SUBMITTED, Actor.CUSTOMER),
        (OrderStatus.PAYMENT_REVIEW, Actor.STAFF),
        (OrderStatus.PAID, Actor.STAFF),
    ):
        transition_order(order=order, target=target, actor_type=actor, user=user, scopes={"*"})
    order.refresh_from_db()
    return order


@pytest.fixture
def dual_bot(dual_order, dual_pool, fake_transport):
    job = run_job(create_job(order=dual_order, strategy="pool"))
    assert job.status == JobStatus.SUCCEEDED, f"{job.error_code}: {job.error_detail}"
    return job.bot


class TestOneBotTwoChannels:
    def test_both_channels_go_live(self, dual_bot):
        assert dual_bot.status == BotStatus.ACTIVE

        platforms = {
            i.platform: i.status for i in dual_bot.instances.all()
        }
        assert platforms == {
            "telegram": BotPlatformInstance.Status.ACTIVE,
            "bale": BotPlatformInstance.Status.ACTIVE,
        }

    def test_it_is_one_bot_not_two(self, dual_bot, dual_order):
        """Two bots would mean two sets of business data to keep in sync."""
        assert Bot.objects.filter(origin_order=dual_order).count() == 1
        assert dual_bot.instances.count() == 2

    def test_each_channel_has_its_own_username_and_link(self, dual_bot):
        telegram = dual_bot.instances.get(platform="telegram")
        bale = dual_bot.instances.get(platform="bale")

        assert telegram.username != bale.username
        assert telegram.link.startswith("https://t.me/")
        assert bale.link.startswith("https://ble.ir/")

    def test_the_configuration_is_shared(self, dual_bot):
        """Spec §3: the customer must not enter their business twice."""
        assert dual_bot.instances.count() == 2
        # One configuration row, reachable from the bot both instances belong to.
        assert dual_bot.configuration is not None
        assert {i.bot_id for i in dual_bot.instances.all()} == {dual_bot.pk}

    def test_features_are_enabled_once_for_both(self, dual_bot):
        slugs = set(dual_bot.bot_features.values_list("feature__slug", flat=True))
        assert {"faq", "contact"} <= slugs
        # One row per feature, not one per channel.
        assert dual_bot.bot_features.count() == len(slugs)

    def test_each_channel_gets_its_own_credential(self, dual_bot):
        """Shared configuration, separate credentials — one token cannot drive both."""
        for instance in dual_bot.instances.all():
            assert hasattr(instance, "credential")

        fingerprints = {i.credential.fingerprint for i in dual_bot.instances.all()}
        assert len(fingerprints) == 2

    def test_each_channel_gets_its_own_webhook(self, dual_bot):
        urls = {i.webhook_url for i in dual_bot.instances.all()}
        assert len(urls) == 2
        assert all("/webhooks/" in url for url in urls)

    def test_the_previously_deferred_platform_now_provisions(self, dual_bot):
        """Phase 4 left Bale instances PENDING. Phase 5 must actually finish them."""
        bale = dual_bot.instances.get(platform="bale")
        assert bale.status == BotPlatformInstance.Status.ACTIVE
        assert bale.username
        assert bale.webhook_set_at is not None


class TestSharedBusinessLogic:
    def test_the_same_question_is_answered_on_both_channels(self, dual_bot, fake_transport):
        """One handler, one set of business data, two channels (spec §61.1)."""
        from apps.bot_runtime.dispatcher import dispatch_update
        from apps.bot_runtime.models import InboundUpdate

        replies = {}
        for index, instance in enumerate(dual_bot.instances.all().order_by("platform")):
            update = InboundUpdate.objects.create(
                instance=instance,
                platform_update_id=500 + index,
                raw={
                    "update_id": 500 + index,
                    "message": {
                        "message_id": 1,
                        "text": "/start",
                        "chat": {"id": 900 + index},
                        "from": {"id": 900 + index, "first_name": "Sara", "language_code": "en"},
                    },
                },
            )
            result = dispatch_update(update)
            replies[instance.platform] = result

        assert set(replies) == {"telegram", "bale"}
        for platform, result in replies.items():
            assert result.handled, platform
            # Same business, same greeting, from one configuration.
            assert "Tehran Smile Clinic" in result.reply_text, platform

    def test_contacts_are_tracked_per_channel(self, dual_bot, fake_transport):
        """A person on Telegram and Bale is two platform identities.

        Merging them without a verified signal would be a privacy problem, so they are
        two `business_contact` rows under one tenant (BALE.md §5).
        """
        from apps.bot_runtime.dispatcher import dispatch_update
        from apps.bot_runtime.models import BusinessContact, InboundUpdate

        for index, instance in enumerate(dual_bot.instances.all().order_by("platform")):
            update = InboundUpdate.objects.create(
                instance=instance,
                platform_update_id=600 + index,
                raw={
                    "update_id": 600 + index,
                    "message": {
                        "message_id": 1,
                        "text": "/start",
                        "chat": {"id": 4242},
                        "from": {"id": 4242, "first_name": "Sara"},
                    },
                },
            )
            dispatch_update(update)

        contacts = BusinessContact.objects.filter(bot=dual_bot, platform_user_id="4242")
        assert contacts.count() == 2
        assert {c.platform for c in contacts} == {"telegram", "bale"}
        # Same tenant — the business sees both under one roof.
        assert {c.tenant_id for c in contacts} == {dual_bot.tenant_id}


class TestPricingStillHolds:
    def test_two_channels_cost_less_than_two_bots(self, catalogue):
        """Spec §9, re-checked now that both channels are genuinely deliverable."""
        single, _ = build_quote(
            template_slug="clinic", platforms=["telegram"], feature_slugs=["faq"], currency="USD"
        )
        both, _ = build_quote(
            template_slug="clinic",
            platforms=["telegram", "bale"],
            feature_slugs=["faq"],
            currency="USD",
        )
        assert single.total_minor < both.total_minor < single.total_minor * 2

    def test_features_are_billed_once_across_channels(self, catalogue):
        both, _ = build_quote(
            template_slug="clinic",
            platforms=["telegram", "bale"],
            feature_slugs=["faq"],
            currency="USD",
        )
        faq_lines = [i for i in both.items.all() if i.feature_slug == "faq"]
        assert len(faq_lines) == 1
