from django.contrib import admin

from apps.features.models import Feature, FeaturePlatformAvailability
from apps.features.registry import all_manifests


class AvailabilityInline(admin.TabularInline):
    model = FeaturePlatformAvailability
    extra = 0


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "category", "is_active", "has_manifest", "sort_order")
    list_filter = ("category", "is_active")
    search_fields = ("slug", "name", "description")
    list_editable = ("is_active", "sort_order")
    inlines = (AvailabilityInline,)
    readonly_fields = ("public_id", "manifest_summary")

    @admin.display(boolean=True, description="Manifest")
    def has_manifest(self, obj: Feature) -> bool:
        return obj.slug in all_manifests()

    @admin.display(description="Manifest")
    def manifest_summary(self, obj: Feature) -> str:
        manifest = all_manifests().get(obj.slug)
        if manifest is None:
            return "No manifest — this feature cannot be routed at runtime."
        return (
            f"requires={list(manifest.requires) or '—'} · "
            f"price_keys={list(manifest.price_keys) or '—'} · "
            f"menu_entries={len(manifest.menu)} · preview_steps={len(manifest.preview)}"
        )


@admin.register(FeaturePlatformAvailability)
class FeaturePlatformAvailabilityAdmin(admin.ModelAdmin):
    """Withdraw a feature from a channel without a deploy (docs/00-ANALYSIS.md R-02)."""

    list_display = ("feature", "platform", "is_available", "degradation_note")
    list_filter = ("platform", "is_available")
    search_fields = ("feature__slug",)
    list_editable = ("is_available",)
