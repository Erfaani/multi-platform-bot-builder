"""The bot runtime: ingress, routing, sessions, dispatch, outbound gateway."""

from __future__ import annotations

import hashlib
import json

import pytest
from django.utils import timezone

from apps.bot_runtime.callbacks import InvalidCallback, decode, encode
from apps.bot_runtime.context import resolve_context
from apps.bot_runtime.models import BusinessContact, InboundUpdate, OutboundMessage
from apps.bot_runtime.sessions import load_session, save_session
from apps.bots.models import BotPlatformInstance, WebhookSecret

pytestmark = pytest.mark.django_db


def message_update(update_id: int, text: str = "/start", user_id: str = "555") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "text": text,
            "chat": {"id": 999},
            "from": {
                "id": int(user_id),
                "first_name": "Ada",
                "username": "ada",
                "language_code": "en",
            },
        },
    }


def issue_secret(instance) -> str:
    secret = "test-webhook-secret-value"
    WebhookSecret.objects.create(
        instance=instance,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        is_active=True,
    )
    return secret


def post_webhook(client, instance, payload: dict, secret: str | None = None):
    headers = {}
    if secret is not None:
        headers["HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN"] = secret
    return client.post(
        f"/webhooks/telegram/{instance.public_id}/",
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )


class TestIngress:
    def test_a_valid_update_is_accepted_and_stored(self, client, active_instance):
        secret = issue_secret(active_instance)
        response = post_webhook(client, active_instance, message_update(1), secret)

        assert response.status_code == 200
        assert InboundUpdate.objects.filter(
            instance=active_instance, platform_update_id=1
        ).exists()

    def test_a_wrong_secret_is_rejected_but_still_answers_200(self, client, active_instance):
        """A non-200 would make Telegram retry something we deliberately dropped."""
        issue_secret(active_instance)
        response = post_webhook(client, active_instance, message_update(2), "wrong-secret")

        assert response.status_code == 200
        assert not InboundUpdate.objects.filter(platform_update_id=2).exists()

    def test_a_missing_secret_is_rejected(self, client, active_instance):
        issue_secret(active_instance)
        post_webhook(client, active_instance, message_update(3))
        assert not InboundUpdate.objects.filter(platform_update_id=3).exists()

    def test_an_unknown_bot_id_reveals_nothing(self, client):
        import uuid

        response = client.post(
            f"/webhooks/telegram/{uuid.uuid4()}/",
            data=json.dumps(message_update(4)),
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_a_suspended_bot_stops_receiving(self, client, active_instance):
        """Suspension has to actually stop the bot, or expiry is cosmetic."""
        secret = issue_secret(active_instance)
        active_instance.status = BotPlatformInstance.Status.SUSPENDED
        active_instance.save(update_fields=["status"])

        post_webhook(client, active_instance, message_update(5), secret)
        assert not InboundUpdate.objects.filter(platform_update_id=5).exists()

    def test_redelivery_is_a_no_op(self, client, active_instance):
        secret = issue_secret(active_instance)
        post_webhook(client, active_instance, message_update(6), secret)
        response = post_webhook(client, active_instance, message_update(6), secret)

        assert response.status_code == 200
        assert InboundUpdate.objects.filter(platform_update_id=6).count() == 1

    def test_two_secrets_are_valid_during_rotation(self, client, active_instance):
        """An update already in flight must not be dropped mid-rotation."""
        old = issue_secret(active_instance)
        new = "rotated-secret-value"
        WebhookSecret.objects.create(
            instance=active_instance,
            secret_hash=hashlib.sha256(new.encode()).hexdigest(),
            is_active=True,
        )

        assert post_webhook(client, active_instance, message_update(7), old).status_code == 200
        assert InboundUpdate.objects.filter(platform_update_id=7).exists()
        post_webhook(client, active_instance, message_update(8), new)
        assert InboundUpdate.objects.filter(platform_update_id=8).exists()

    def test_malformed_json_is_swallowed(self, client, active_instance):
        secret = issue_secret(active_instance)
        response = client.post(
            f"/webhooks/telegram/{active_instance.public_id}/",
            data="not json",
            content_type="application/json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=secret,
        )
        assert response.status_code == 200

    def test_get_is_not_allowed(self, client, active_instance):
        assert client.get(f"/webhooks/telegram/{active_instance.public_id}/").status_code == 405


class TestAdapterParsing:
    def test_a_command_is_recognised(self, active_instance):
        from apps.platforms.telegram.adapter import TelegramAdapter

        event = TelegramAdapter().parse(message_update(10, "/start"), "abc")
        assert event.kind == "command"
        assert event.chat_ref == "999"
        assert event.user_ref == "555"
        assert event.locale_hint == "en"

    def test_plain_text_is_a_message(self, active_instance):
        from apps.platforms.telegram.adapter import TelegramAdapter

        assert TelegramAdapter().parse(message_update(11, "hello"), "abc").kind == "message"

    def test_a_callback_is_recognised(self):
        from apps.platforms.telegram.adapter import TelegramAdapter

        raw = {
            "update_id": 12,
            "callback_query": {
                "id": "cb1",
                "data": "v1.abc.core:menu.",
                "from": {"id": 555, "first_name": "Ada"},
                "message": {"message_id": 3, "chat": {"id": 999}},
            },
        }
        event = TelegramAdapter().parse(raw, "abc")
        assert event.kind == "callback"
        assert event.payload["data"] == "v1.abc.core:menu."


class TestCallbackSigning:
    def test_a_payload_round_trips(self):
        payload = encode("instance-1", "faq:list", "42")
        assert decode("instance-1", payload) == ("faq:list", "42")

    def test_a_tampered_payload_is_refused(self):
        payload = encode("instance-1", "faq:list", "42")
        with pytest.raises(InvalidCallback):
            decode("instance-1", payload.replace("faq:list", "admin:delete"))

    def test_a_payload_from_another_bot_is_refused(self):
        """Keyed per instance, so a token minted for one bot cannot be replayed."""
        payload = encode("instance-1", "faq:list", "42")
        with pytest.raises(InvalidCallback):
            decode("instance-2", payload)

    def test_an_oversized_payload_fails_at_build_time(self):
        """Telegram silently rejects buttons over 64 bytes — fail in tests instead."""
        with pytest.raises(InvalidCallback):
            encode("instance-1", "feature:" + "x" * 80, "value")


class TestContextResolution:
    def test_the_context_carries_the_bot_and_tenant(self, active_instance):
        ctx = resolve_context(active_instance)
        assert ctx.bot_id == active_instance.bot_id
        assert ctx.tenant_id == active_instance.bot.tenant_id
        assert ctx.platform == "telegram"

    def test_purchased_features_are_present(self, active_instance):
        ctx = resolve_context(active_instance)
        assert ctx.has_feature("faq")
        assert not ctx.has_feature("appointment")

    def test_a_configuration_change_invalidates_the_cache(self, active_instance):
        first = resolve_context(active_instance)

        configuration = active_instance.bot.configuration
        configuration.welcome_message = "Totally new greeting"
        configuration.save(update_fields=["welcome_message"])
        configuration.bump()

        active_instance.bot.refresh_from_db()
        second = resolve_context(active_instance)

        assert second.configuration_version > first.configuration_version
        assert second.welcome_message == "Totally new greeting"


class TestDispatch:
    def _dispatch(self, instance, payload):
        from apps.bot_runtime.dispatcher import dispatch_update

        update = InboundUpdate.objects.create(
            instance=instance, platform_update_id=payload["update_id"], raw=payload
        )
        return dispatch_update(update)

    def test_start_produces_a_welcome_and_a_menu(self, active_instance, fake_transport):
        result = self._dispatch(active_instance, message_update(20, "/start"))

        assert result.handled
        assert "Tehran Smile Clinic" in result.reply_text

        sent = OutboundMessage.objects.get(instance=active_instance)
        assert sent.status == OutboundMessage.Status.SENT
        assert sent.payload["reply_markup"] is not None

    def test_the_end_user_is_recorded_as_a_contact_not_a_platform_user(
        self, active_instance, fake_transport
    ):
        from apps.accounts.models import User

        self._dispatch(active_instance, message_update(21))

        contact = BusinessContact.objects.get(bot=active_instance.bot, platform_user_id="555")
        assert contact.tenant_id == active_instance.bot.tenant_id
        assert contact.display_name == "Ada"
        # A clinic's patients must never appear in the accounts table.
        assert not User.objects.filter(email__contains="555").exists()

    def test_an_unknown_message_falls_back_to_the_menu(self, active_instance, fake_transport):
        result = self._dispatch(active_instance, message_update(22, "asdfghjkl"))
        assert result.route == "core:menu"

    def test_a_menu_label_routes_to_its_feature(self, active_instance, fake_transport):
        result = self._dispatch(active_instance, message_update(23, "Contact"))
        assert result.route == "business:contact"
        assert "+98 21 1234 5678" in result.reply_text

    def test_tapping_a_rendered_choice_reaches_its_sub_value(self, active_instance, fake_transport):
        """A button built from `Reply.choices` must round-trip through a real tap.

        `faq:list` packs the entry id onto the route as `faq:list.<id>` (the only way a
        list-then-detail flow can offer a value per row). If the render path ever stops
        splitting that back into `(route, value)` before signing, every such button falls
        back to the main menu instead of reaching the handler with its value — silently,
        since the callback still verifies and still resolves to a real, allowed route.
        """
        from apps.businesses.models import FaqEntry

        entry = FaqEntry.objects.create(
            tenant=active_instance.bot.tenant,
            bot=active_instance.bot,
            question="Do you take walk-ins?",
            answer="Yes, weekdays only.",
        )

        listed = self._dispatch(active_instance, message_update(23, "FAQ"))
        assert listed.route == "faq:list"

        # The real callback_data Telegram would hand back on a tap — not a hand-rolled
        # equivalent, so this actually exercises the signing path in `_render()`.
        sent = OutboundMessage.objects.filter(instance=active_instance).latest("created_at")
        buttons = sent.payload["reply_markup"]["inline_keyboard"]
        payload = next(
            button["callback_data"]
            for row in buttons
            for button in row
            if button["text"] == entry.question
        )
        raw = {
            "update_id": 231,
            "callback_query": {
                "id": "cb",
                "data": payload,
                "from": {"id": 555, "first_name": "Ada"},
                "message": {"message_id": 1, "chat": {"id": 999}},
            },
        }
        result = self._dispatch(active_instance, raw)
        assert result.route == "faq:list"
        assert entry.answer in result.reply_text

    def test_a_route_for_an_unbought_feature_is_refused(self, active_instance, fake_transport):
        """A signed callback from before a feature was removed must stop working."""
        payload = encode(str(active_instance.public_id), "appointment:book", "")
        raw = {
            "update_id": 24,
            "callback_query": {
                "id": "cb",
                "data": payload,
                "from": {"id": 555, "first_name": "Ada"},
                "message": {"message_id": 1, "chat": {"id": 999}},
            },
        }
        result = self._dispatch(active_instance, raw)
        assert result.route == "core:menu"

    def test_an_unsigned_callback_is_refused(self, active_instance, fake_transport):
        raw = {
            "update_id": 25,
            "callback_query": {
                "id": "cb",
                "data": "v1.deadbeef.business:contact.",
                "from": {"id": 555, "first_name": "Ada"},
                "message": {"message_id": 1, "chat": {"id": 999}},
            },
        }
        result = self._dispatch(active_instance, raw)
        assert result.route == "core:menu"

    def test_a_handler_failure_still_answers_the_user(
        self, active_instance, fake_transport, monkeypatch
    ):
        """Silence is the worst outcome — the user must be told something went wrong."""
        from apps.businesses import handlers as business_handlers

        def explode(*args, **kwargs):
            raise RuntimeError("handler blew up")

        monkeypatch.setattr(business_handlers, "contact", explode)
        from apps.bot_runtime import handlers as registry

        # The router stores the function object at registration time, not a live
        # attribute lookup, so patching `business_handlers.contact` above does not
        # reach it — the registry entry has to be patched too. `monkeypatch.setitem`
        # (not a raw dict assignment) so this reverts after the test instead of
        # leaking into whichever test runs next.
        monkeypatch.setitem(registry._ROUTES, "business:contact", explode)

        result = self._dispatch(active_instance, message_update(26, "Contact"))

        assert not result.handled
        assert OutboundMessage.objects.filter(instance=active_instance).exists()

        active_instance.bot.refresh_from_db()
        assert active_instance.bot.error_count == 1

    def test_the_update_is_marked_processed(self, active_instance, fake_transport):
        self._dispatch(active_instance, message_update(27))
        update = InboundUpdate.objects.get(platform_update_id=27)
        assert update.status == InboundUpdate.Status.PROCESSED


class TestSessions:
    def test_a_session_round_trips(self, provisioned_bot):
        session = load_session(
            bot_id=provisioned_bot.pk, platform="telegram", chat_ref="1", user_ref="2"
        )
        session.state = "appointment.awaiting_slot"
        session.set("service_id", 7)
        save_session(session)

        reloaded = load_session(
            bot_id=provisioned_bot.pk, platform="telegram", chat_ref="1", user_ref="2"
        )
        assert reloaded.state == "appointment.awaiting_slot"
        assert reloaded.get("service_id") == 7

    def test_an_expired_session_is_reported_as_stale(self, provisioned_bot):
        """So the bot can explain the reset instead of misreading the next message."""
        from datetime import timedelta

        from apps.bot_runtime.models import BotSession
        from django.core.cache import cache

        session = load_session(
            bot_id=provisioned_bot.pk, platform="telegram", chat_ref="3", user_ref="4"
        )
        session.state = "appointment.awaiting_slot"
        save_session(session)

        cache.clear()
        BotSession.objects.filter(bot=provisioned_bot, chat_ref="3").update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        reloaded = load_session(
            bot_id=provisioned_bot.pk, platform="telegram", chat_ref="3", user_ref="4"
        )
        assert reloaded.is_idle
        assert reloaded.was_stale


class TestOutboundGateway:
    def test_a_send_is_recorded_before_dispatch(self, active_instance, fake_transport):
        from apps.bot_runtime.gateway import deliver
        from apps.platforms.base import RenderedMessage

        outbound = deliver(
            instance=active_instance, chat_ref="999", message=RenderedMessage(text="hello")
        )
        assert outbound.status == OutboundMessage.Status.SENT
        assert outbound.platform_message_id

    def test_rate_limiting_defers_rather_than_drops(self, active_instance, fake_transport):
        from django.test import override_settings

        from apps.bot_runtime.gateway import deliver
        from apps.platforms.base import RenderedMessage

        with override_settings(OUTBOUND_RATE_PER_CHAT_PER_SECOND=1):
            first = deliver(
                instance=active_instance, chat_ref="777", message=RenderedMessage(text="one")
            )
            second = deliver(
                instance=active_instance, chat_ref="777", message=RenderedMessage(text="two")
            )

        assert first.status == OutboundMessage.Status.SENT
        assert second.status == OutboundMessage.Status.QUEUED
        assert second.next_attempt_at is not None

    def test_a_blocked_user_is_not_retried_forever(self, active_instance, fake_transport):
        from apps.bot_runtime.gateway import deliver
        from apps.platforms.base import RenderedMessage
        from apps.platforms.transport import PlatformApiError

        BusinessContact.objects.create(
            tenant=active_instance.bot.tenant,
            bot=active_instance.bot,
            platform="telegram",
            platform_user_id="999",
        )
        fake_transport.failures["sendMessage"] = PlatformApiError(
            "Forbidden: bot was blocked by the user", status_code=403
        )

        outbound = deliver(
            instance=active_instance, chat_ref="999", message=RenderedMessage(text="hi")
        )

        assert outbound.status == OutboundMessage.Status.DROPPED
        contact = BusinessContact.objects.get(bot=active_instance.bot, platform_user_id="999")
        assert contact.is_blocked

    def test_a_platform_429_honours_retry_after(self, active_instance, fake_transport):
        from apps.bot_runtime.gateway import deliver
        from apps.platforms.base import RenderedMessage
        from apps.platforms.transport import PlatformApiError

        fake_transport.failures["sendMessage"] = PlatformApiError(
            "Too Many Requests", status_code=429, retry_after=42
        )
        outbound = deliver(
            instance=active_instance, chat_ref="888", message=RenderedMessage(text="hi")
        )

        assert outbound.status == OutboundMessage.Status.QUEUED
        delay = (outbound.next_attempt_at - timezone.now()).total_seconds()
        assert 35 < delay <= 42

    def test_a_transient_error_retries_with_backoff(self, active_instance, fake_transport):
        from apps.bot_runtime.gateway import deliver
        from apps.platforms.base import RenderedMessage
        from apps.platforms.transport import PlatformApiError

        fake_transport.failures["sendMessage"] = PlatformApiError("boom", status_code=500)
        outbound = deliver(
            instance=active_instance, chat_ref="666", message=RenderedMessage(text="hi")
        )

        assert outbound.status == OutboundMessage.Status.QUEUED
        assert outbound.attempt == 1
