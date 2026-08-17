from __future__ import annotations

from rest_framework import serializers

from apps.business_templates.models import BusinessTemplate
from apps.i18n_content.services import translate as translate_content


class TemplateFeatureSerializer(serializers.Serializer):
    slug = serializers.CharField(source="feature.slug")
    is_default = serializers.BooleanField()
    is_required = serializers.BooleanField()
    sort_order = serializers.IntegerField()


class BusinessTemplateSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    name = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    features = serializers.SerializerMethodField()
    default_features = serializers.SerializerMethodField()
    required_features = serializers.SerializerMethodField()

    class Meta:
        model = BusinessTemplate
        fields = (
            "id",
            "slug",
            "icon",
            "name",
            "description",
            "features",
            "default_features",
            "required_features",
            "sort_order",
        )

    def _locale(self) -> str:
        return self.context.get("locale", "en")

    def get_name(self, obj: BusinessTemplate) -> str:
        return translate_content(obj, "name", locale=self._locale(), source=obj.name)

    def get_description(self, obj: BusinessTemplate) -> str:
        return translate_content(
            obj, "description", locale=self._locale(), source=obj.description
        )

    def get_features(self, obj: BusinessTemplate) -> list[dict]:
        rows = obj.template_features.select_related("feature").filter(feature__is_active=True)
        return TemplateFeatureSerializer(rows, many=True).data

    def get_default_features(self, obj: BusinessTemplate) -> list[str]:
        return obj.default_feature_slugs()

    def get_required_features(self, obj: BusinessTemplate) -> list[str]:
        return obj.required_feature_slugs()
