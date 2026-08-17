"""Business templates (spec §10).

A template is a *curated starting point*: which features are offered, which are on by
default, and which are mandatory for the vertical to make sense. It is data, so adding
"Veterinary Clinic" is an admin task rather than a release.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PublicIdModel, TimeStampedModel
from apps.features.models import Feature


class BusinessTemplate(PublicIdModel, TimeStampedModel):
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=64, blank=True)

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    features = models.ManyToManyField(
        Feature, through="TemplateFeature", related_name="templates"
    )

    class Meta:
        db_table = "business_template"
        ordering = ("sort_order", "slug")

    def __str__(self) -> str:
        return self.slug

    @property
    def base_price_key(self) -> str:
        return f"template.{self.slug}.base"

    def default_feature_slugs(self) -> list[str]:
        return list(
            self.template_features.filter(models.Q(is_default=True) | models.Q(is_required=True))
            .order_by("sort_order")
            .values_list("feature__slug", flat=True)
        )

    def required_feature_slugs(self) -> list[str]:
        return list(
            self.template_features.filter(is_required=True).values_list("feature__slug", flat=True)
        )


class TemplateFeature(TimeStampedModel):
    template = models.ForeignKey(
        BusinessTemplate, on_delete=models.CASCADE, related_name="template_features"
    )
    feature = models.ForeignKey(
        Feature, on_delete=models.CASCADE, related_name="template_features"
    )

    is_default = models.BooleanField(
        default=False, help_text=_("Pre-selected in the builder; the customer may remove it.")
    )
    is_required = models.BooleanField(
        default=False,
        help_text=_("Cannot be removed — the template is meaningless without it."),
    )
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "template_feature"
        ordering = ("sort_order",)
        constraints = [
            models.UniqueConstraint(
                fields=["template", "feature"], name="template_feature_uniq"
            )
        ]

    def __str__(self) -> str:
        return f"{self.template.slug}/{self.feature.slug}"
