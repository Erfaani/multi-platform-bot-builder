from __future__ import annotations

from rest_framework import serializers

from apps.crm.models import ContactNote, Feedback, Lead, LeadStatus


class ContactNoteSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    author_email = serializers.EmailField(source="author.email", read_only=True, default=None)

    class Meta:
        model = ContactNote
        fields = ("id", "author_email", "body", "created_at")
        read_only_fields = fields


class LeadSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    contact_name = serializers.CharField(source="contact.display_name", read_only=True)
    assigned_to_email = serializers.EmailField(source="assigned_to.email", read_only=True, default=None)
    notes = ContactNoteSerializer(many=True, read_only=True)
    tags = serializers.SlugRelatedField(slug_field="name", many=True, read_only=True)

    class Meta:
        model = Lead
        fields = (
            "id", "source", "status", "message", "phone", "contact_name",
            "assigned_to_email", "notes", "tags", "created_at",
        )
        read_only_fields = fields


class LeadUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=LeadStatus.choices, required=False)
    assigned_to_id = serializers.IntegerField(required=False, allow_null=True)


class AddNoteSerializer(serializers.Serializer):
    body = serializers.CharField()


class TagLeadSerializer(serializers.Serializer):
    tag = serializers.CharField(max_length=64)


class FeedbackSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    contact_name = serializers.CharField(source="contact.display_name", read_only=True)

    class Meta:
        model = Feedback
        fields = ("id", "rating", "comment", "contact_name", "created_at")
        read_only_fields = fields
