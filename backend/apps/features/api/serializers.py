from __future__ import annotations

from rest_framework import serializers

from apps.features.models import Feature
from apps.features.registry import all_manifests
from apps.i18n_content.services import translate as translate_content
from apps.platforms.constants import SELLABLE_PLATFORMS


class FeatureSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    name = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    requires = serializers.SerializerMethodField()
    always_on = serializers.SerializerMethodField()
    platforms = serializers.SerializerMethodField()

    class Meta:
        model = Feature
        fields = (
            "id",
            "slug",
            "category",
            "icon",
            "name",
            "description",
            "requires",
            "always_on",
            "platforms",
            "sort_order",
        )

    def _locale(self) -> str:
        return self.context.get("locale", "en")

    def get_name(self, obj: Feature) -> str:
        return translate_content(obj, "name", locale=self._locale(), source=obj.name)

    def get_description(self, obj: Feature) -> str:
        return translate_content(
            obj, "description", locale=self._locale(), source=obj.description
        )

    def get_requires(self, obj: Feature) -> list[str]:
        manifest = all_manifests().get(obj.slug)
        return list(manifest.requires) if manifest else []

    def get_always_on(self, obj: Feature) -> bool:
        manifest = all_manifests().get(obj.slug)
        return bool(manifest and manifest.always_on)

    def get_platforms(self, obj: Feature) -> dict:
        """Per-platform availability, so the builder can disable rather than fail."""
        matrix = self.context.get("availability", {})
        entries = matrix.get(obj.slug, [])
        return {
            entry.platform: {
                "available": entry.is_available,
                "reason": entry.reason,
                "note": entry.note,
            }
            for entry in entries
        }


class PlatformSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    capabilities_verified = serializers.BooleanField()


def platform_payload() -> list[dict]:
    from apps.platforms.registry import get_adapter

    payload = []
    for slug in SELLABLE_PLATFORMS:
        adapter = get_adapter(slug)
        payload.append(
            {
                "slug": slug,
                "name": getattr(adapter, "display_name", slug.title()),
                "capabilities_verified": adapter.capabilities.verified,
            }
        )
    return payload
