"""AI assistant configuration, knowledge base, and per-bot usage tracking (Phase 8).

Two tiers, gated by two feature slugs (`apps/ai/manifest.py`):

- `ai_assistant` (Tier 1) grounds every answer in `BusinessProfile` + active `FaqEntry`
  rows, stuffed directly into the prompt — a small business's profile and FAQ list
  comfortably fits in a single prompt, so no retrieval infrastructure is needed for it
  (`apps.ai.services.answer_question`).
- `ai_knowledge_base` (Tier 2, requires `ai_assistant`) adds uploaded documents that are
  too large to stuff whole; those are chunked and embedded so only the most relevant
  passages are retrieved per question (`KnowledgeChunk`, pgvector cosine search).

Budgets are enforced per bot, not aggregated across a tenant's bots: `ai_assistant` is
purchased per bot (`BotFeature`), like every other feature in this codebase, so per-bot is
the unit a customer actually pays for and can see exhausted. See PHASES.md for the full
reasoning behind this scope decision.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _
from pgvector.django import HnswIndex, VectorField

from apps.ai.embeddings import EMBEDDING_DIMENSIONS
from apps.core.models import PublicIdModel, TenantOwnedModel


class AiConfiguration(TenantOwnedModel):
    """Per-bot AI settings: the customer's own instructions and their token budget."""

    bot = models.OneToOneField(
        "bots.Bot", on_delete=models.CASCADE, related_name="ai_configuration"
    )
    custom_instructions = models.TextField(
        blank=True,
        help_text=_("Extra rules the assistant must follow, e.g. tone, things never to promise."),
    )
    #: `None` -> the platform default (`settings.AI_DEFAULT_MONTHLY_TOKEN_BUDGET`). Always
    #: clamped to `settings.AI_HARD_MONTHLY_TOKEN_BUDGET_CAP` regardless of this value —
    #: see `apps.ai.services.effective_budget`.
    monthly_token_budget = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "ai_configuration"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"AI configuration for bot {self.bot_id}"


class KnowledgeDocument(PublicIdModel, TenantOwnedModel):
    """An uploaded knowledge-base document (`ai_knowledge_base` tier).

    Ingestion accepts plain text only (pasted, or a `.txt` upload) — parsing PDF/DOCX is a
    documented gap (PHASES.md "Not built in Phase 8"), out of scope for this phase.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        READY = "READY", _("Ready")
        FAILED = "FAILED", _("Failed")

    bot = models.ForeignKey(
        "bots.Bot", on_delete=models.CASCADE, related_name="knowledge_documents"
    )
    title = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    error_message = models.CharField(max_length=500, blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "ai_knowledge_document"
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.title


class KnowledgeChunk(TenantOwnedModel):
    """One retrievable passage of a `KnowledgeDocument`, with its embedding."""

    bot = models.ForeignKey(
        "bots.Bot", on_delete=models.CASCADE, related_name="knowledge_chunks"
    )
    document = models.ForeignKey(
        KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks"
    )
    position = models.PositiveIntegerField()
    text = models.TextField()
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)

    class Meta:
        db_table = "ai_knowledge_chunk"
        ordering = ("document_id", "position")
        indexes = [
            models.Index(fields=["bot", "document"], name="ai_chunk_bot_document_idx"),
            HnswIndex(
                name="ai_chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.document_id}#{self.position}"


class AiUsageRecord(TenantOwnedModel):
    """One answered (or refused) question — the ledger `services.py` budgets against."""

    bot = models.ForeignKey(
        "bots.Bot", on_delete=models.CASCADE, related_name="ai_usage_records"
    )
    contact = models.ForeignKey(
        "bot_runtime.BusinessContact",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    model = models.CharField(max_length=64, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    #: Whether an uploaded document was actually retrieved and used (Tier 2). Business
    #: profile/FAQ grounding (Tier 1) is present on every answered question once the
    #: feature is bought, so it isn't tracked separately here.
    used_knowledge_base = models.BooleanField(default=False)

    class Meta:
        db_table = "ai_usage_record"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["bot", "-created_at"], name="ai_usage_bot_created_idx")]

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
