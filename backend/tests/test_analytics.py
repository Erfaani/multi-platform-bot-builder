"""Minimal real analytics (spec §31): every inbound message leaves a trace."""

from __future__ import annotations

import pytest

from apps.analytics.models import AnalyticsEvent, EventType
from apps.analytics.services import bot_summary, record_event
from apps.bot_runtime.dispatcher import dispatch_update
from apps.bot_runtime.models import InboundUpdate

pytestmark = pytest.mark.django_db


def _message(update_id: int, text: str, user_id: str = "555") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "text": text,
            "chat": {"id": 999},
            "from": {"id": int(user_id), "first_name": "Ada", "username": "ada", "language_code": "en"},
        },
    }


def _dispatch(instance, payload):
    update = InboundUpdate.objects.create(
        instance=instance, platform_update_id=payload["update_id"], raw=payload
    )
    return dispatch_update(update)


class TestRecordEvent:
    def test_a_command_is_recorded_as_command_used(self, provisioned_bot, fake_transport):
        instance = provisioned_bot.instances.get(platform="telegram")
        _dispatch(instance, _message(1, "/start"))

        event = AnalyticsEvent.objects.get(bot=provisioned_bot)
        assert event.event_type == EventType.COMMAND_USED
        assert event.label == "/start"

    def test_a_plain_message_is_recorded_as_message_received(self, provisioned_bot, fake_transport):
        instance = provisioned_bot.instances.get(platform="telegram")
        _dispatch(instance, _message(2, "Contact"))

        event = AnalyticsEvent.objects.get(bot=provisioned_bot)
        assert event.event_type == EventType.MESSAGE_RECEIVED

    def test_the_event_is_linked_to_the_contact(self, provisioned_bot, fake_transport):
        from apps.bot_runtime.models import BusinessContact

        instance = provisioned_bot.instances.get(platform="telegram")
        _dispatch(instance, _message(3, "/start"))

        contact = BusinessContact.objects.get(bot=provisioned_bot, platform_user_id="555")
        event = AnalyticsEvent.objects.get(bot=provisioned_bot)
        assert event.contact_id == contact.pk

    def test_a_failure_is_swallowed_not_raised(self, monkeypatch):
        """Analytics must never be the reason a customer's message goes unanswered."""

        def _boom(**kwargs):
            raise RuntimeError("database is on fire")

        monkeypatch.setattr(AnalyticsEvent.objects, "create", _boom)
        record_event(tenant_id=1, bot_id=1, event_type=EventType.MESSAGE_RECEIVED)
        # No exception means the contract held; nothing else to assert.


class TestBotSummary:
    def test_counts_reflect_recorded_events(self, provisioned_bot, fake_transport):
        instance = provisioned_bot.instances.get(platform="telegram")
        _dispatch(instance, _message(10, "/start"))
        _dispatch(instance, _message(11, "Contact"))

        summary = bot_summary(provisioned_bot)
        assert summary["messages_7d"] == 1  # only the plain message counts as MESSAGE_RECEIVED
        assert summary["total_contacts"] == 1

    def test_daily_series_covers_the_full_window_with_zero_fill(self, provisioned_bot, fake_transport):
        summary = bot_summary(provisioned_bot)
        assert len(summary["daily_messages"]) == 14
        assert all("date" in point and "count" in point for point in summary["daily_messages"])

    def test_a_bot_with_no_activity_reports_zeroes(self, provisioned_bot):
        summary = bot_summary(provisioned_bot)
        assert summary["total_contacts"] == 0
        assert summary["messages_7d"] == 0
        assert sum(p["count"] for p in summary["daily_messages"]) == 0


class TestAnalyticsApi:
    def test_owner_can_read_the_summary(self, auth_client, provisioned_bot, fake_transport):
        instance = provisioned_bot.instances.get(platform="telegram")
        _dispatch(instance, _message(20, "Contact"))

        response = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/analytics/")
        assert response.status_code == 200
        assert response.json()["messages_7d"] == 1

    def test_a_stranger_cannot_read_another_tenants_analytics(self, other_client, provisioned_bot):
        response = other_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/analytics/")
        assert response.status_code == 404
