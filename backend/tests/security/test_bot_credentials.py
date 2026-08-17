"""Bot credential custody (SECURITY.md §5).

A bot token grants total control of a customer's bot. These tests exist to keep it
encrypted, unique, unlogged and unserialized.
"""

from __future__ import annotations

import re

import pytest

from apps.bots.credentials import (
    CredentialError,
    add_pool_entry,
    read_token,
    store_token,
    validate_token_shape,
)
from apps.bots.models import BotCredential
from apps.core.errors import ConflictError, ValidationError

pytestmark = pytest.mark.django_db

TOKEN = "7000000123:AA-real-looking-token-cccccccccccccccc"
TOKEN_SHAPE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")


class TestStorage:
    def test_a_token_round_trips(self, active_instance):
        store_token(instance=active_instance, token=TOKEN)
        assert read_token(instance=active_instance, purpose="test") == TOKEN

    def test_the_plaintext_is_not_in_the_database(self, active_instance):
        store_token(instance=active_instance, token=TOKEN)
        credential = BotCredential.objects.get(instance=active_instance)
        assert TOKEN.encode() not in bytes(credential.ciphertext)

    def test_a_malformed_token_is_refused(self, active_instance):
        with pytest.raises(ValidationError):
            store_token(instance=active_instance, token="nonsense")

    def test_the_same_token_cannot_serve_two_workspaces(
        self, active_instance, provisioned_bot, catalogue
    ):
        """Otherwise two customers would share one bot and see each other's chats."""
        from apps.bots.models import Bot, BotPlatformInstance

        other_bot = Bot.objects.create(
            tenant=provisioned_bot.tenant,
            template=provisioned_bot.template,
            name="Another bot",
        )
        other_instance = BotPlatformInstance.objects.create(
            bot=other_bot, platform="telegram", acquisition_mode="TOKEN_HANDOFF"
        )

        store_token(instance=active_instance, token=TOKEN)
        with pytest.raises(ConflictError) as exc:
            store_token(instance=other_instance, token=TOKEN)
        assert exc.value.code == "bots.token_already_registered"

    def test_ciphertext_is_bound_to_its_instance(self, active_instance, provisioned_bot):
        """A credential row copied to another instance must not decrypt.

        Belt and braces against a database-level mix-up handing one customer another's
        bot.
        """
        from apps.bots.models import Bot, BotPlatformInstance

        store_token(instance=active_instance, token=TOKEN)
        source = BotCredential.objects.get(instance=active_instance)

        other_bot = Bot.objects.create(
            tenant=provisioned_bot.tenant, template=provisioned_bot.template, name="Other"
        )
        other_instance = BotPlatformInstance.objects.create(
            bot=other_bot, platform="telegram", acquisition_mode="POOL"
        )
        BotCredential.objects.create(
            instance=other_instance,
            ciphertext=source.ciphertext,
            fingerprint="a-different-fingerprint",
        )
        other_instance.refresh_from_db()

        with pytest.raises(CredentialError):
            read_token(instance=other_instance, purpose="test")

    def test_reading_a_missing_credential_raises(self, provisioned_bot):
        from apps.bots.models import Bot, BotPlatformInstance

        bot = Bot.objects.create(
            tenant=provisioned_bot.tenant, template=provisioned_bot.template, name="Bare"
        )
        instance = BotPlatformInstance.objects.create(
            bot=bot, platform="telegram", acquisition_mode="POOL"
        )
        with pytest.raises(CredentialError):
            read_token(instance=instance, purpose="test")


class TestPool:
    def test_a_duplicate_pool_token_is_refused(self, db, fake_transport):
        add_pool_entry(platform="telegram", username="pool_one_bot", token=TOKEN)
        with pytest.raises(ConflictError):
            add_pool_entry(platform="telegram", username="pool_two_bot", token=TOKEN)

    def test_a_pool_token_already_assigned_is_refused(self, active_instance, fake_transport):
        store_token(instance=active_instance, token=TOKEN)
        with pytest.raises(ConflictError):
            add_pool_entry(platform="telegram", username="pool_three_bot", token=TOKEN)


class TestNoLeakage:
    def test_the_bots_api_never_returns_a_token(self, auth_client, provisioned_bot, tenant_a):
        response = auth_client.get("/api/v1/bots/")
        body = response.content.decode()
        assert TOKEN_SHAPE.search(body) is None
        assert "token" not in body.lower() or "tokens" not in body.lower()

    def test_the_bot_detail_never_returns_a_token(
        self, auth_client, provisioned_bot, tenant_a
    ):
        response = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/")
        assert TOKEN_SHAPE.search(response.content.decode()) is None

    def test_the_credential_str_reveals_nothing(self, active_instance):
        store_token(instance=active_instance, token=TOKEN)
        credential = BotCredential.objects.get(instance=active_instance)
        assert TOKEN not in str(credential)
        assert TOKEN not in repr(credential)

    def test_a_token_is_redacted_if_it_ever_reaches_a_log(self):
        from apps.core.logging import redact

        assert TOKEN_SHAPE.search(redact(f"calling api with {TOKEN}")) is None


class TestValidation:
    @pytest.mark.parametrize("bad", ["", "   ", "abc", "1234567890", "no-colon-here-at-all"])
    def test_obviously_wrong_tokens_are_refused(self, bad):
        with pytest.raises(ValidationError):
            validate_token_shape(bad)

    def test_a_plausible_token_is_accepted(self):
        assert validate_token_shape(f"  {TOKEN}  ") == TOKEN
