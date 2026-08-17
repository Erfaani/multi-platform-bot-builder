from django.contrib import admin

from apps.business_templates.models import BusinessTemplate, TemplateFeature


class TemplateFeatureInline(admin.TabularInline):
    model = TemplateFeature
    extra = 0
    autocomplete_fields = ("feature",)
    ordering = ("sort_order",)


@admin.register(BusinessTemplate)
class BusinessTemplateAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "is_active", "feature_count", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("slug", "name", "description")
    list_editable = ("is_active", "sort_order")
    readonly_fields = ("public_id", "base_price_key")
    inlines = (TemplateFeatureInline,)

    @admin.display(description="Features")
    def feature_count(self, obj: BusinessTemplate) -> int:
        return obj.template_features.count()


@admin.register(TemplateFeature)
class TemplateFeatureAdmin(admin.ModelAdmin):
    list_display = ("template", "feature", "is_required", "is_default", "sort_order")
    list_filter = ("is_required", "is_default", "template")
    search_fields = ("template__slug", "feature__slug")
    autocomplete_fields = ("template", "feature")
