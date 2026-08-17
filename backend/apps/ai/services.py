"""AI assistant orchestration: configuration, ingestion, retrieval, and budgeted answering.

Grounding is two-tiered (see `models.py`):

- Tier 1 (`ai_assistant`): the business profile and every active FAQ entry are stuffed
  directly into the system prompt — small enough that retrieval would be over-engineering.
- Tier 2 (`ai_knowledge_base`): uploaded documents are chunked and embedded at ingest time;
  at answer time the top-matching chunks are retrieved by pgvector cosine search and
  appended to the same prompt.

Either way the model is told, explicitly and every time, to answer *only* from what it was
given and to say so plainly when the context doesn't cover the question — the "I don't
know" behaviour the exit criterion asks for. A cheaper gate sits in front of that: if a bot
has no grounding at all (no profile, no FAQ, no matching chunks), the provider is never
called — there is nothing to answer from, so paying for a request that could only
apologise would be wasted spend.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services import record_audit
from apps.bots.models import Bot
from apps.businesses.models import BusinessProfile, FaqEntry
from apps.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from apps.core.events import publish
from apps.core.models import SystemSetting

from apps.ai.embeddings import chunk_text, embed_text
from apps.ai.models import AiConfiguration, AiUsageRecord, KnowledgeChunk, KnowledgeDocument
from apps.ai.providers import AiProviderError, get_provider

#: Characters, not tokens — a cheap, dependency-free proxy that keeps the Tier-1 prompt
#: bounded even for a business with dozens of FAQ entries.
MAX_CONTEXT_CHARS = 6000
RETRIEVAL_TOP_K = 4
#: pgvector's `<=>` cosine-distance operator (1 - similarity) — lower is more similar.
#: Deliberately loose: the local hashed-bag-of-words embedding (`apps/ai/embeddings.py`)
#: only picks up literal token overlap, not semantic similarity, so its distances run much
#: higher than a real embeddings model's for genuinely related text. This threshold still
#: excludes chunks with *zero* shared vocabulary (which land at ~1.0); a real embeddings
#: provider would let it tighten considerably.
RETRIEVAL_MAX_DISTANCE = 0.9

SYSTEM_PROMPT_TEMPLATE = """You are the automated assistant for {business_name}, answering \
questions from customers in a chat conversation. Answer ONLY using the information given \
below under "Business knowledge" — never invent facts, prices, hours, or policies that \
aren't there. If the answer isn't in that information, say plainly that you don't know and \
suggest the customer contact the business directly. Keep answers short and conversational, \
suitable for a chat message. Respond in the same language the customer wrote in.
{custom_instructions}
Business knowledge:
{context}"""


@dataclass(frozen=True, slots=True)
class AiAnswer:
    text: str | None
    grounded: bool
    budget_exceeded: bool = False
    provider_error: bool = False


# --------------------------------------------------------------------------- configuration


def get_or_create_configuration(bot: Bot) -> AiConfiguration:
    config, _created = AiConfiguration.objects.get_or_create(
        bot=bot, defaults={"tenant": bot.tenant}
    )
    return config


@transaction.atomic
def update_configuration(*, bot: Bot, actor, **fields) -> AiConfiguration:
    config = get_or_create_configuration(bot)

    changed: list[str] = []
    if "custom_instructions" in fields and fields["custom_instructions"] is not None:
        config.custom_instructions = fields["custom_instructions"][:4000]
        changed.append("custom_instructions")
    if "monthly_token_budget" in fields and fields["monthly_token_budget"] is not None:
        budget = fields["monthly_token_budget"]
        if budget < 0:
            raise ValidationError(
                code="ai.invalid_budget",
                field_errors={"monthly_token_budget": ["Must not be negative."]},
            )
        config.monthly_token_budget = min(budget, settings.AI_HARD_MONTHLY_TOKEN_BUDGET_CAP)
        changed.append("monthly_token_budget")

    if changed:
        config.save(update_fields=[*changed, "updated_at"])
        record_audit(
            actor=actor,
            action="ai.configuration_updated",
            resource_type="ai_configuration",
            resource_id=str(config.pk),
            tenant=bot.tenant,
            metadata={"fields": changed},
        )
    return config


def get_configured_model() -> str:
    """A platform admin's override (`SystemSetting` key `ai.model`), else `settings.AI_MODEL`.

    This is Phase 8's "admin model configuration" — a superuser edits one `SystemSetting`
    row in Django admin to move every tenant onto a different Claude model, no deploy
    required.
    """
    setting = SystemSetting.objects.filter(key="ai.model").first()
    if setting and isinstance(setting.value, dict) and setting.value.get("model"):
        return str(setting.value["model"])
    return settings.AI_MODEL


# --------------------------------------------------------------------------- budget


def _period_start(now: dt.datetime | None = None) -> dt.datetime:
    now = now or timezone.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def effective_budget(bot: Bot) -> int:
    config = AiConfiguration.objects.filter(bot=bot).first()
    # `is not None`, not truthiness: a customer setting the budget to exactly 0 (to hard-
    # block the assistant) must not silently fall back to the platform default.
    budget = config.monthly_token_budget if config and config.monthly_token_budget is not None else None
    if budget is None:
        budget = settings.AI_DEFAULT_MONTHLY_TOKEN_BUDGET
    return min(budget, settings.AI_HARD_MONTHLY_TOKEN_BUDGET_CAP)


def usage_this_period(bot: Bot) -> int:
    totals = AiUsageRecord.objects.filter(bot=bot, created_at__gte=_period_start()).aggregate(
        input_total=Sum("input_tokens"), output_total=Sum("output_tokens")
    )
    return (totals["input_total"] or 0) + (totals["output_total"] or 0)


def remaining_budget(bot: Bot) -> int:
    return max(effective_budget(bot) - usage_this_period(bot), 0)


def record_usage(
    *,
    bot: Bot,
    contact,
    input_tokens: int,
    output_tokens: int,
    model: str,
    used_knowledge_base: bool,
) -> AiUsageRecord:
    return AiUsageRecord.objects.create(
        tenant=bot.tenant,
        bot=bot,
        contact=contact,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        used_knowledge_base=used_knowledge_base,
    )


def list_usage(bot: Bot, *, limit: int = 50) -> list[AiUsageRecord]:
    return list(AiUsageRecord.objects.filter(bot=bot).select_related("contact")[:limit])


# --------------------------------------------------------------------------- Tier 1: profile + FAQ


def _business_context_block(bot: Bot) -> str:
    profile = BusinessProfile.objects.filter(bot=bot).first()
    if profile is None:
        return ""

    name = profile.display_name or bot.name
    lines = [f"Business name: {name}"] if name else []
    if profile.description:
        lines.append(f"About: {profile.description}")
    if profile.working_hours_text:
        lines.append(f"Hours: {profile.working_hours_text}")
    if profile.phone:
        lines.append(f"Phone: {profile.phone}")
    if profile.email:
        lines.append(f"Email: {profile.email}")
    if profile.address:
        lines.append(f"Address: {profile.address}")
    return "\n".join(lines)


def _faq_context_block(bot: Bot) -> str:
    entries = FaqEntry.objects.filter(bot=bot, is_active=True).order_by("sort_order", "id")
    return "\n\n".join(f"Q: {entry.question}\nA: {entry.answer}" for entry in entries)


# --------------------------------------------------------------------------- Tier 2: documents


def search_document_chunks(
    bot: Bot, query: str, *, top_k: int = RETRIEVAL_TOP_K
) -> list[KnowledgeChunk]:
    from pgvector.django import CosineDistance

    query_vector = embed_text(query)
    chunks = (
        KnowledgeChunk.objects.filter(bot=bot)
        .annotate(distance=CosineDistance("embedding", query_vector))
        .filter(distance__lte=RETRIEVAL_MAX_DISTANCE)
        .order_by("distance")[:top_k]
    )
    return list(chunks)


@transaction.atomic
def ingest_document(*, bot: Bot, actor, title: str, content: str) -> KnowledgeDocument:
    if not bot.has_feature("ai_knowledge_base"):
        raise PermissionDeniedError(code="ai.knowledge_base_not_enabled")

    title = title.strip()
    content = content.strip()
    if not title:
        raise ValidationError(
            code="ai.document_title_required", field_errors={"title": ["A title is required."]}
        )
    if not content:
        raise ValidationError(
            code="ai.document_content_required", field_errors={"content": ["Content is required."]}
        )
    if len(content) > settings.AI_MAX_DOCUMENT_CHARS:
        raise ValidationError(
            code="ai.document_too_long",
            field_errors={
                "content": [f"Keep it under {settings.AI_MAX_DOCUMENT_CHARS} characters."]
            },
        )

    document = KnowledgeDocument.objects.create(
        tenant=bot.tenant,
        bot=bot,
        title=title[:255],
        content_type="text/plain",
        status=KnowledgeDocument.Status.PENDING,
        uploaded_by=actor if getattr(actor, "pk", None) else None,
    )

    pieces = chunk_text(content)
    if not pieces:
        document.status = KnowledgeDocument.Status.FAILED
        document.error_message = "No content to index."
        document.save(update_fields=["status", "error_message", "updated_at"])
        return document

    KnowledgeChunk.objects.bulk_create(
        KnowledgeChunk(
            tenant=bot.tenant,
            bot=bot,
            document=document,
            position=index,
            text=piece,
            embedding=embed_text(piece),
        )
        for index, piece in enumerate(pieces)
    )
    document.status = KnowledgeDocument.Status.READY
    document.chunk_count = len(pieces)
    document.save(update_fields=["status", "chunk_count", "updated_at"])

    record_audit(
        actor=actor,
        action="ai.document_ingested",
        resource_type="knowledge_document",
        resource_id=str(document.public_id),
        tenant=bot.tenant,
        metadata={"chunks": len(pieces)},
    )
    return document


def list_documents(bot: Bot) -> list[KnowledgeDocument]:
    return list(KnowledgeDocument.objects.filter(bot=bot))


@transaction.atomic
def delete_document(*, bot: Bot, document_id, actor) -> None:
    document = KnowledgeDocument.objects.filter(bot=bot, public_id=document_id).first()
    if document is None:
        raise NotFoundError()

    document.delete()
    record_audit(
        actor=actor,
        action="ai.document_deleted",
        resource_type="knowledge_document",
        resource_id=str(document_id),
        tenant=bot.tenant,
    )


# --------------------------------------------------------------------------- answering


def answer_question(*, bot: Bot, contact, question: str, locale: str = "en") -> AiAnswer:
    question = (question or "").strip()
    if not question:
        return AiAnswer(text=None, grounded=False)

    if usage_this_period(bot) >= effective_budget(bot):
        publish(
            "ai.budget_exceeded",
            {
                "tenant_id": str(bot.tenant.public_id),
                "bot_id": str(bot.public_id),
                "dedupe_key": f"ai_budget:{bot.public_id}:{_period_start().date().isoformat()}",
            },
        )
        return AiAnswer(text=None, grounded=False, budget_exceeded=True)

    context_parts = [
        part for part in (_business_context_block(bot), _faq_context_block(bot)) if part
    ]

    used_knowledge_base = False
    if bot.has_feature("ai_knowledge_base"):
        chunks = search_document_chunks(bot, question)
        if chunks:
            used_knowledge_base = True
            context_parts.append("\n\n".join(chunk.text for chunk in chunks))

    context = "\n\n".join(context_parts)[:MAX_CONTEXT_CHARS]
    if not context.strip():
        # Nothing configured to ground an answer in — never call the provider for this;
        # there is nothing it could answer from except its own training data, which is
        # exactly what the exit criterion forbids.
        return AiAnswer(text=None, grounded=False)

    config = get_or_create_configuration(bot)
    system = SYSTEM_PROMPT_TEMPLATE.format(
        business_name=bot.name,
        custom_instructions=f"\n{config.custom_instructions}\n" if config.custom_instructions else "",
        context=context,
    )

    try:
        response = get_provider().generate(
            system=system, question=question, model=get_configured_model()
        )
    except AiProviderError:
        return AiAnswer(text=None, grounded=True, provider_error=True)

    record_usage(
        bot=bot,
        contact=contact,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        model=response.model,
        used_knowledge_base=used_knowledge_base,
    )
    return AiAnswer(text=response.text or None, grounded=True)
