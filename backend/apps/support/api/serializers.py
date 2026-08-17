from __future__ import annotations

from rest_framework import serializers

from apps.support.models import SupportAttachment, SupportMessage, SupportTicket


class SupportAttachmentSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = SupportAttachment
        fields = ("id", "original_filename", "content_type", "size_bytes", "url", "created_at")

    def get_url(self, obj: SupportAttachment) -> str:
        request = self.context.get("request")
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url


class SupportMessageSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    author_email = serializers.SerializerMethodField()
    attachments = SupportAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = SupportMessage
        fields = ("id", "author_type", "author_email", "body", "attachments", "created_at")

    def get_author_email(self, obj: SupportMessage) -> str | None:
        return obj.author.email if obj.author_id else None


class SupportTicketSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    bot = serializers.UUIDField(source="bot.public_id", read_only=True, default=None)
    created_by_email = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = (
            "id",
            "bot",
            "subject",
            "status",
            "priority",
            "created_by_email",
            "last_reply_at",
            "created_at",
        )

    def get_created_by_email(self, obj: SupportTicket) -> str | None:
        return obj.created_by.email if obj.created_by_id else None


class SupportTicketDetailSerializer(SupportTicketSerializer):
    messages = serializers.SerializerMethodField()

    class Meta(SupportTicketSerializer.Meta):
        fields = SupportTicketSerializer.Meta.fields + ("messages",)

    def get_messages(self, obj: SupportTicket) -> list:
        from apps.support.services import list_messages

        return SupportMessageSerializer(
            list_messages(obj), many=True, context=self.context
        ).data


class TicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=255)
    body = serializers.CharField()
    bot = serializers.UUIDField(required=False, allow_null=True)


class TicketReplySerializer(serializers.Serializer):
    body = serializers.CharField()
    file = serializers.FileField(required=False)
