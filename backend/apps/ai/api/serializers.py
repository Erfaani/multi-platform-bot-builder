from __future__ import annotations

from rest_framework import serializers

from apps.ai.models import AiConfiguration, AiUsageRecord, KnowledgeDocument


class AiConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AiConfiguration
        fields = ("custom_instructions", "monthly_token_budget")
        read_only_fields = fields


class AiConfigurationUpdateSerializer(serializers.Serializer):
    custom_instructions = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    monthly_token_budget = serializers.IntegerField(required=False, allow_null=True, min_value=0)


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = KnowledgeDocument
        fields = ("id", "title", "content_type", "status", "error_message", "chunk_count", "created_at")
        read_only_fields = fields


class KnowledgeDocumentCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    content = serializers.CharField()


class AiUsageRecordSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    total_tokens = serializers.IntegerField(read_only=True)

    class Meta:
        model = AiUsageRecord
        fields = (
            "id", "model", "input_tokens", "output_tokens", "total_tokens",
            "used_knowledge_base", "created_at",
        )
        read_only_fields = fields


class AiUsageSummarySerializer(serializers.Serializer):
    used_tokens = serializers.IntegerField()
    budget = serializers.IntegerField()
    remaining = serializers.IntegerField()
