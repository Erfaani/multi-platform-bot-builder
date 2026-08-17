from django.contrib import admin

from apps.ai.models import AiConfiguration, AiUsageRecord, KnowledgeChunk, KnowledgeDocument


@admin.register(AiConfiguration)
class AiConfigurationAdmin(admin.ModelAdmin):
    list_display = ("bot", "monthly_token_budget", "updated_at")
    search_fields = ("bot__name",)
    autocomplete_fields = ("tenant", "bot")


class KnowledgeChunkInline(admin.TabularInline):
    model = KnowledgeChunk
    extra = 0
    fields = ("position", "text")
    readonly_fields = ("position", "text")
    can_delete = False


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "bot", "status", "chunk_count", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "bot__name", "public_id")
    readonly_fields = ("public_id", "chunk_count", "created_at", "updated_at")
    autocomplete_fields = ("tenant", "bot", "uploaded_by")
    inlines = (KnowledgeChunkInline,)


@admin.register(AiUsageRecord)
class AiUsageRecordAdmin(admin.ModelAdmin):
    list_display = ("bot", "model", "input_tokens", "output_tokens", "used_knowledge_base", "created_at")
    list_filter = ("used_knowledge_base", "model")
    search_fields = ("bot__name",)
    autocomplete_fields = ("tenant", "bot", "contact")
    readonly_fields = ("created_at",)
