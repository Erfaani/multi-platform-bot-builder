"""Bot-level self-service settings: configuration fields and webhook rotation.

Both are customer self-service, distinct from `test_business_profile.py` (what the
bot *says*) — this is what the bot *is*: its name/locale/timezone, and the live
webhook connecting it to the platform.
"""

from __future__ import annotations

import pytest

from apps.bots.models import BotPlatformInstance

pytestmark = pytest.mark.django_db


def _bot_url(bot, suffix: str = "") -> str:
    return f"/api/v1/bots/{bot.public_id}/{suffix}"


class TestBotConfiguration:
    def test_owner_can_update_name_locale_and_timezone(self, auth_client, provisioned_bot):
        response = auth_client.patch(
            _bot_url(provisioned_bot, "configuration/"),
            {"name": "Renamed Clinic Bot", "default_locale": "fa", "timezone": "Asia/Tehran"},
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Renamed Clinic Bot"
        assert body["default_locale"] == "fa"
        assert body["timezone"] == "Asia/Tehran"

        provisioned_bot.refresh_from_db()
        assert provisioned_bot.name == "Renamed Clinic Bot"
        assert provisioned_bot.timezone == "Asia/Tehran"

    def test_a_stranger_cannot_configure_another_tenants_bot(self, other_client, provisioned_bot):
        response = other_client.patch(
            _bot_url(provisioned_bot, "configuration/"), {"name": "Hijacked"}, format="json"
        )
        assert response.status_code == 404


class TestWebhookRotation:
    def test_owner_can_rotate_the_webhook(self, auth_client, provisioned_bot, active_instance, fake_transport):
        before = active_instance.webhook_set_at
        fake_transport.calls.clear()

        response = auth_client.post(
            _bot_url(provisioned_bot, f"instances/{active_instance.public_id}/rotate-webhook/")
        )
        assert response.status_code == 200
        assert fake_transport.called("setWebhook")

        active_instance.refresh_from_db()
        assert active_instance.webhook_set_at > before

    def test_rotating_an_awaiting_token_instance_is_rejected(self, auth_client, provisioned_bot, active_instance):
        active_instance.status = BotPlatformInstance.Status.AWAITING_TOKEN
        active_instance.save(update_fields=["status"])

        response = auth_client.post(
            _bot_url(provisioned_bot, f"instances/{active_instance.public_id}/rotate-webhook/")
        )
        assert response.status_code == 409

    def test_a_stranger_cannot_rotate_another_tenants_webhook(self, other_client, provisioned_bot, active_instance):
        response = other_client.post(
            _bot_url(provisioned_bot, f"instances/{active_instance.public_id}/rotate-webhook/")
        )
        assert response.status_code == 404

    def test_a_platform_rejection_is_a_clean_error_not_a_crash(
        self, auth_client, provisioned_bot, active_instance, fake_transport
    ):
        from apps.platforms.transport import PlatformApiError

        fake_transport.failures["setWebhook"] = PlatformApiError("Unauthorized", method="setWebhook")

        response = auth_client.post(
            _bot_url(provisioned_bot, f"instances/{active_instance.public_id}/rotate-webhook/")
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "bots.webhook_rotation_failed"


class TestInputRestrictionsApi:
    def test_defaults_to_unrestricted(self, auth_client, provisioned_bot):
        response = auth_client.get(_bot_url(provisioned_bot, "input-restrictions/"))
        assert response.status_code == 200
        body = response.json()
        assert body["allowed_calling_codes"] == []
        assert body["collect_email_on_consultation"] is False

    def test_owner_can_set_restrictions(self, auth_client, provisioned_bot):
        response = auth_client.patch(
            _bot_url(provisioned_bot, "input-restrictions/"),
            {
                "allowed_calling_codes": ["+98", "+1"],
                "blocked_phone_numbers": ["+1 555 010 0100"],
                "collect_email_on_consultation": True,
                "blocked_email_domains": ["Spam.Example"],
            },
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["allowed_calling_codes"] == ["+1", "+98"]
        # normalised to digits-only and lowercase respectively, for exact matching later
        assert body["blocked_phone_numbers"] == ["15550100100"]
        assert body["blocked_email_domains"] == ["spam.example"]
        assert body["collect_email_on_consultation"] is True

    def test_a_stranger_cannot_read_another_tenants_restrictions(self, other_client, provisioned_bot):
        response = other_client.get(_bot_url(provisioned_bot, "input-restrictions/"))
        assert response.status_code == 404
