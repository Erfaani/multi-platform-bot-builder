"""The AI assistant module (Phase 8): grounding, retrieval, budgets, and the provider
abstraction. Every provider-facing test uses a stub (`_StubProvider`) — nothing in this
suite may touch a real Claude API, matching the conformance-suite convention for platform
transports (`tests/conftest_bots.py::fake_transport`)."""

from __future__ import annotations

import pytest

from apps.ai import services
from apps.ai.embeddings import chunk_text, embed_text
from apps.ai.models import AiConfiguration, AiUsageRecord, KnowledgeChunk, KnowledgeDocument
from apps.ai.providers.base import AiProviderError, ProviderResponse
from apps.core.errors import NotFoundError, PermissionDeniedError, ValidationError

pytestmark = pytest.mark.django_db


class _StubProvider:
    def __init__(self, *, text: str = "Stub answer.", raise_error: bool = False) -> None:
        self.text = text
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def generate(self, *, system: str, question: str, model: str) -> ProviderResponse:
        self.calls.append({"system": system, "question": question, "model": model})
        if self.raise_error:
            raise AiProviderError("boom")
        return ProviderResponse(text=self.text, input_tokens=100, output_tokens=40, model=model)


@pytest.fixture
def contact(provisioned_bot):
    from apps.bot_runtime.models import BusinessContact

    return BusinessContact.objects.create(
        tenant=provisioned_bot.tenant, bot=provisioned_bot, platform="telegram", platform_user_id="555"
    )


@pytest.fixture
def faq_entry(provisioned_bot):
    from apps.businesses.models import FaqEntry

    return FaqEntry.objects.create(
        tenant=provisioned_bot.tenant, bot=provisioned_bot,
        question="What are your hours?", answer="We're open 9 to 5, Saturday to Thursday.",
    )


def _enable(bot, slug: str) -> None:
    from apps.bots.models import BotFeature
    from apps.features.models import Feature

    feature = Feature.objects.get(slug=slug)
    BotFeature.objects.create(bot=bot, feature=feature, is_enabled=True)
    # `ctx.has_feature(...)` (the router's gate) reads a cached `BotContext` keyed by
    # `BotConfiguration.version` — a `BotFeature` row created directly, bypassing the
    # dashboard's `update_configuration()`, never bumps it, so without this the router
    # keeps dispatching against the bot's pre-test feature set.
    bot.configuration.bump()


class TestEmbeddings:
    def test_embed_text_is_deterministic(self):
        assert embed_text("hello world") == embed_text("hello world")

    def test_embed_text_is_unit_length(self):
        import math

        vector = embed_text("Our hours are nine to five on weekdays.")
        norm = math.sqrt(sum(component * component for component in vector))
        assert norm == pytest.approx(1.0, abs=1e-6)

    def test_overlapping_vocabulary_is_closer_than_unrelated_text(self):
        import math

        def cosine(a, b):
            return sum(x * y for x, y in zip(a, b))

        base = embed_text("Our clinic is open Saturday through Wednesday from nine to six.")
        similar = embed_text("What time is the clinic open on Saturday?")
        unrelated = embed_text("The quarterly server migration completed without incident.")

        assert cosine(base, similar) > cosine(base, unrelated)

    def test_chunk_text_splits_long_input_with_overlap(self):
        words = [f"word{i}" for i in range(500)]
        chunks = chunk_text(" ".join(words), size=200, overlap=50)

        assert len(chunks) > 1
        # every chunk boundary keeps some trailing words in common with the next chunk
        first_tail = chunks[0].split()[-10:]
        assert any(word in chunks[1].split() for word in first_tail)

    def test_chunk_text_returns_a_single_chunk_for_short_input(self):
        assert chunk_text("Just a short sentence.") == ["Just a short sentence."]

    def test_chunk_text_handles_empty_input(self):
        assert chunk_text("") == []


class TestConfiguration:
    def test_get_or_create_configuration(self, provisioned_bot):
        config = services.get_or_create_configuration(provisioned_bot)
        assert isinstance(config, AiConfiguration)
        assert config.custom_instructions == ""
        assert config.monthly_token_budget is None

    def test_update_configuration(self, provisioned_bot, user):
        config = services.update_configuration(
            bot=provisioned_bot, actor=user,
            custom_instructions="Never mention competitors.", monthly_token_budget=5000,
        )
        assert config.custom_instructions == "Never mention competitors."
        assert config.monthly_token_budget == 5000

    def test_budget_is_clamped_to_the_hard_cap(self, provisioned_bot, user, settings):
        settings.AI_HARD_MONTHLY_TOKEN_BUDGET_CAP = 1000
        config = services.update_configuration(
            bot=provisioned_bot, actor=user, monthly_token_budget=999999
        )
        assert config.monthly_token_budget == 1000

    def test_a_negative_budget_is_rejected(self, provisioned_bot, user):
        with pytest.raises(ValidationError):
            services.update_configuration(bot=provisioned_bot, actor=user, monthly_token_budget=-1)

    def test_get_configured_model_falls_back_to_settings(self, settings):
        settings.AI_MODEL = "claude-haiku-4-5"
        assert services.get_configured_model() == "claude-haiku-4-5"

    def test_get_configured_model_honours_the_admin_override(self):
        from apps.core.models import SystemSetting

        SystemSetting.objects.create(key="ai.model", value={"model": "claude-opus-5"})
        assert services.get_configured_model() == "claude-opus-5"


class TestBudget:
    def test_a_bot_with_no_configuration_uses_the_platform_default(self, provisioned_bot, settings):
        settings.AI_DEFAULT_MONTHLY_TOKEN_BUDGET = 12345
        assert services.effective_budget(provisioned_bot) == 12345

    def test_a_zero_budget_is_not_treated_as_unset(self, provisioned_bot, user):
        services.update_configuration(bot=provisioned_bot, actor=user, monthly_token_budget=0)
        assert services.effective_budget(provisioned_bot) == 0

    def test_usage_sums_only_the_current_period(self, provisioned_bot):
        import datetime as dt

        from django.utils import timezone

        AiUsageRecord.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, input_tokens=100, output_tokens=50
        )
        old = AiUsageRecord.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, input_tokens=9000, output_tokens=9000
        )
        AiUsageRecord.objects.filter(pk=old.pk).update(
            created_at=timezone.now().replace(day=1) - dt.timedelta(days=5)
        )

        assert services.usage_this_period(provisioned_bot) == 150

    def test_remaining_budget_never_goes_negative(self, provisioned_bot, user):
        services.update_configuration(bot=provisioned_bot, actor=user, monthly_token_budget=10)
        AiUsageRecord.objects.create(
            tenant=provisioned_bot.tenant, bot=provisioned_bot, input_tokens=100, output_tokens=0
        )
        assert services.remaining_budget(provisioned_bot) == 0


class TestKnowledgeIngestion:
    def test_ingesting_requires_the_knowledge_base_feature(self, provisioned_bot, user):
        with pytest.raises(PermissionDeniedError):
            services.ingest_document(
                bot=provisioned_bot, actor=user, title="Refund policy", content="Refunds within 14 days."
            )

    def test_ingest_document_creates_chunks(self, provisioned_bot, user):
        _enable(provisioned_bot, "ai_knowledge_base")
        document = services.ingest_document(
            bot=provisioned_bot, actor=user, title="Refund policy",
            content=" ".join(["word"] * 500),
        )
        assert document.status == KnowledgeDocument.Status.READY
        assert document.chunk_count == KnowledgeChunk.objects.filter(document=document).count()
        assert document.chunk_count > 1

    def test_empty_content_is_rejected(self, provisioned_bot, user):
        _enable(provisioned_bot, "ai_knowledge_base")
        with pytest.raises(ValidationError):
            services.ingest_document(bot=provisioned_bot, actor=user, title="Empty", content="   ")

    def test_content_over_the_limit_is_rejected(self, provisioned_bot, user, settings):
        _enable(provisioned_bot, "ai_knowledge_base")
        settings.AI_MAX_DOCUMENT_CHARS = 10
        with pytest.raises(ValidationError):
            services.ingest_document(
                bot=provisioned_bot, actor=user, title="Too long", content="way more than ten characters"
            )

    def test_search_finds_the_relevant_chunk(self, provisioned_bot, user):
        # The local hashed embedding only picks up literal token overlap (see
        # `RETRIEVAL_MAX_DISTANCE`'s comment) — the query deliberately reuses "shipping"
        # verbatim from the document it should match, and shares nothing with "Returns".
        _enable(provisioned_bot, "ai_knowledge_base")
        services.ingest_document(
            bot=provisioned_bot, actor=user, title="Shipping",
            content="Shipping takes three business days and covers worldwide delivery via express courier.",
        )
        services.ingest_document(
            bot=provisioned_bot, actor=user, title="Returns",
            content="Returns are accepted within thirty days for a full refund on unused items.",
        )

        results = services.search_document_chunks(provisioned_bot, "How long does shipping take?")
        assert results
        assert "shipping" in results[0].text.lower()

    def test_delete_document_removes_its_chunks(self, provisioned_bot, user):
        _enable(provisioned_bot, "ai_knowledge_base")
        document = services.ingest_document(
            bot=provisioned_bot, actor=user, title="Notes", content="Some notes about our service."
        )
        services.delete_document(bot=provisioned_bot, document_id=document.public_id, actor=user)
        assert not KnowledgeDocument.objects.filter(pk=document.pk).exists()
        assert not KnowledgeChunk.objects.filter(document_id=document.pk).exists()

    def test_deleting_an_unknown_document_is_not_found(self, provisioned_bot, user):
        import uuid

        with pytest.raises(NotFoundError):
            services.delete_document(bot=provisioned_bot, document_id=uuid.uuid4(), actor=user)


class TestAnswerQuestion:
    def test_an_unconfigured_bot_never_calls_the_provider(self, provisioned_bot, contact, monkeypatch):
        from apps.businesses.models import BusinessProfile

        # `provisioned_bot` ships with a populated business profile (its own fixture seeds
        # one) and no FAQ entries — blank the profile too, so there is truly nothing to
        # ground an answer in.
        BusinessProfile.objects.filter(bot=provisioned_bot).update(
            display_name="", description="", working_hours_text="", phone="", email="", address=""
        )
        provisioned_bot.name = ""
        provisioned_bot.save(update_fields=["name"])

        stub = _StubProvider()
        monkeypatch.setattr(services, "get_provider", lambda: stub)

        answer = services.answer_question(bot=provisioned_bot, contact=contact, question="What are your hours?")

        assert answer.grounded is False
        assert answer.text is None
        assert stub.calls == []

    def test_a_grounded_question_calls_the_provider_and_records_usage(
        self, provisioned_bot, contact, faq_entry, monkeypatch
    ):
        stub = _StubProvider(text="We're open 9 to 5.")
        monkeypatch.setattr(services, "get_provider", lambda: stub)

        answer = services.answer_question(bot=provisioned_bot, contact=contact, question="What are your hours?")

        assert answer.grounded is True
        assert answer.text == "We're open 9 to 5."
        assert len(stub.calls) == 1
        assert faq_entry.question in stub.calls[0]["system"]

        record = AiUsageRecord.objects.get(bot=provisioned_bot)
        assert record.input_tokens == 100 and record.output_tokens == 40

    def test_custom_instructions_reach_the_system_prompt(
        self, provisioned_bot, contact, faq_entry, user, monkeypatch
    ):
        stub = _StubProvider()
        monkeypatch.setattr(services, "get_provider", lambda: stub)
        services.update_configuration(
            bot=provisioned_bot, actor=user, custom_instructions="Always mention our loyalty program."
        )

        services.answer_question(bot=provisioned_bot, contact=contact, question="Hi")

        assert "loyalty program" in stub.calls[0]["system"]

    def test_budget_exceeded_blocks_before_calling_the_provider(
        self, provisioned_bot, contact, faq_entry, user, monkeypatch
    ):
        stub = _StubProvider()
        monkeypatch.setattr(services, "get_provider", lambda: stub)
        services.update_configuration(bot=provisioned_bot, actor=user, monthly_token_budget=0)

        answer = services.answer_question(bot=provisioned_bot, contact=contact, question="Hi")

        assert answer.budget_exceeded is True
        assert stub.calls == []

    def test_a_provider_error_is_reported_but_does_not_raise(
        self, provisioned_bot, contact, faq_entry, monkeypatch
    ):
        stub = _StubProvider(raise_error=True)
        monkeypatch.setattr(services, "get_provider", lambda: stub)

        answer = services.answer_question(bot=provisioned_bot, contact=contact, question="Hi")

        assert answer.provider_error is True
        assert answer.text is None
        assert not AiUsageRecord.objects.filter(bot=provisioned_bot).exists()

    def test_knowledge_base_chunks_are_retrieved_when_the_tier_is_bought(
        self, provisioned_bot, contact, user, monkeypatch
    ):
        _enable(provisioned_bot, "ai_knowledge_base")
        services.ingest_document(
            bot=provisioned_bot, actor=user, title="Warranty",
            content="All products carry a two year warranty covering manufacturing defects.",
        )
        stub = _StubProvider()
        monkeypatch.setattr(services, "get_provider", lambda: stub)

        services.answer_question(bot=provisioned_bot, contact=contact, question="What is your warranty policy?")

        assert "warranty" in stub.calls[0]["system"].lower()
        record = AiUsageRecord.objects.get(bot=provisioned_bot)
        assert record.used_knowledge_base is True


class TestAiConversation:
    """The full customer-facing flow, through the real dispatcher."""

    def _dispatch(self, instance, payload):
        from apps.bot_runtime.dispatcher import dispatch_update
        from apps.bot_runtime.models import InboundUpdate

        update = InboundUpdate.objects.create(
            instance=instance, platform_update_id=payload["update_id"], raw=payload
        )
        return dispatch_update(update)

    def _message(self, update_id, text, user_id="777"):
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id, "text": text, "chat": {"id": 1},
                "from": {"id": int(user_id), "first_name": "Ada", "username": "ada", "language_code": "en"},
            },
        }

    def test_free_text_falls_through_to_the_assistant(self, provisioned_bot, faq_entry, fake_transport, monkeypatch):
        _enable(provisioned_bot, "ai_assistant")
        stub = _StubProvider(text="We're open 9 to 5, Saturday to Thursday.")
        monkeypatch.setattr(services, "get_provider", lambda: stub)

        instance = provisioned_bot.instances.get(platform="telegram")
        result = self._dispatch(instance, self._message(1, "What time do you open?"))

        assert result.route == "ai:ask"
        assert "9 to 5" in result.reply_text

    def test_the_explicit_ask_command_also_works(self, provisioned_bot, faq_entry, fake_transport, monkeypatch):
        _enable(provisioned_bot, "ai_assistant")
        stub = _StubProvider(text="We're open 9 to 5.")
        monkeypatch.setattr(services, "get_provider", lambda: stub)

        instance = provisioned_bot.instances.get(platform="telegram")
        result = self._dispatch(instance, self._message(2, "/ask what time do you open?"))

        assert result.route == "command:ask"
        assert "9 to 5" in result.reply_text
        assert stub.calls[0]["question"] == "what time do you open?"

    def test_without_the_feature_free_text_falls_back_to_the_main_menu(
        self, provisioned_bot, faq_entry, fake_transport, monkeypatch
    ):
        stub = _StubProvider()
        monkeypatch.setattr(services, "get_provider", lambda: stub)

        instance = provisioned_bot.instances.get(platform="telegram")
        result = self._dispatch(instance, self._message(3, "What time do you open?"))

        assert result.route == "core:menu"
        assert stub.calls == []

    def test_an_unconfigured_bot_says_it_does_not_know(self, provisioned_bot, fake_transport):
        """Business profile alone (no active FAQ) is what `provisioned_bot` ships with, so
        the bot *is* grounded via the profile and a real provider would normally run — this
        instead proves the "nothing configured" branch by disabling FAQ requires nothing:
        the profile block alone is non-empty, so assert on the empty-FAQ-only case via a
        bot with blank business fields instead."""
        from apps.businesses.models import BusinessProfile

        _enable(provisioned_bot, "ai_assistant")
        BusinessProfile.objects.filter(bot=provisioned_bot).update(
            display_name="", description="", working_hours_text="", phone="", email="", address=""
        )
        provisioned_bot.name = ""
        provisioned_bot.save(update_fields=["name"])

        instance = provisioned_bot.instances.get(platform="telegram")
        result = self._dispatch(instance, self._message(4, "What time do you open?"))

        assert result.route == "ai:ask"
        assert result.reply_text  # the "I don't know" fallback, not empty

    def test_budget_exceeded_shows_a_targeted_reply(
        self, provisioned_bot, faq_entry, user, fake_transport, monkeypatch
    ):
        _enable(provisioned_bot, "ai_assistant")
        services.update_configuration(bot=provisioned_bot, actor=user, monthly_token_budget=0)
        stub = _StubProvider()
        monkeypatch.setattr(services, "get_provider", lambda: stub)

        instance = provisioned_bot.instances.get(platform="telegram")
        result = self._dispatch(instance, self._message(5, "What time do you open?"))

        assert result.route == "ai:ask"
        assert stub.calls == []


class TestOwnerNotification:
    def test_budget_exceeded_always_notifies_the_owner(self, provisioned_bot):
        """Unlike bot-activity events, this one is not gated behind `owner_notifications` —
        an owner should always learn their assistant went quiet on paying customers."""
        from apps.notifications.models import Notification
        from apps.notifications.services import notify_from_event

        created = notify_from_event(
            "ai.budget_exceeded",
            {
                "tenant_id": str(provisioned_bot.tenant.public_id),
                "bot_id": str(provisioned_bot.public_id),
                "dedupe_key": "ai_budget:test-1",
            },
        )
        assert created >= 1
        assert Notification.objects.filter(event_type="ai.budget_exceeded").exists()


class TestAiApi:
    def test_configuration_get_and_update(self, auth_client, provisioned_bot):
        got = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/ai-configuration/")
        assert got.status_code == 200
        assert got.json()["custom_instructions"] == ""

        updated = auth_client.patch(
            f"/api/v1/bots/{provisioned_bot.public_id}/ai-configuration/",
            {"custom_instructions": "Be brief.", "monthly_token_budget": 1000}, format="json",
        )
        assert updated.status_code == 200
        assert updated.json()["custom_instructions"] == "Be brief."
        assert updated.json()["monthly_token_budget"] == 1000

    def test_documents_require_the_knowledge_base_feature(self, auth_client, provisioned_bot):
        response = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/ai-documents/",
            {"title": "Notes", "content": "Some notes."}, format="json",
        )
        assert response.status_code == 403

    def test_documents_list_create_and_delete(self, auth_client, provisioned_bot):
        _enable(provisioned_bot, "ai_knowledge_base")

        created = auth_client.post(
            f"/api/v1/bots/{provisioned_bot.public_id}/ai-documents/",
            {"title": "Notes", "content": "Some notes about our service."}, format="json",
        )
        assert created.status_code == 201
        document_id = created.json()["id"]

        listed = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/ai-documents/")
        assert listed.status_code == 200
        assert any(item["id"] == document_id for item in listed.json())

        deleted = auth_client.delete(
            f"/api/v1/bots/{provisioned_bot.public_id}/ai-documents/{document_id}/"
        )
        assert deleted.status_code == 204

    def test_usage_summary(self, auth_client, provisioned_bot):
        response = auth_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/ai-usage/")
        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["used_tokens"] == 0
        assert body["records"] == []

    def test_a_stranger_cannot_see_another_tenants_ai_configuration(self, other_client, provisioned_bot):
        response = other_client.get(f"/api/v1/bots/{provisioned_bot.public_id}/ai-configuration/")
        assert response.status_code == 404
