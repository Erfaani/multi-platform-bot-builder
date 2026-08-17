"""Feature catalogue.

The row is the *sellable* record — active, priced, orderable. The manifest is the
*behavioural* record — menus, handlers, requirements. They are joined by `slug` and a
system check fails startup when they disagree (ARCHITECTURE.md §5).
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PublicIdModel, TimeStampedModel
from apps.platforms.constants import Platform


class Feature(PublicIdModel, TimeStampedModel):
    slug = models.SlugField(max_length=64, unique=True)
    category = models.CharField(max_length=32, db_index=True)
    icon = models.CharField(max_length=64, blank=True)

    #: Source-locale text; translations live in `i18n_content` (I18N.md §1).
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "feature"
        ordering = ("sort_order", "slug")

    def __str__(self) -> str:
        return self.slug

    @property
    def manifest(self):
        from apps.features.registry import get_manifest

        return get_manifest(self.slug)


class FeaturePlatformAvailability(TimeStampedModel):
    """Whether a feature may be sold on a platform, and why not if it may not.

    Data rather than code, so operations can withdraw a feature from a channel the
    moment a limitation is discovered — without a deploy (docs/00-ANALYSIS.md R-02).
    """

    feature = models.ForeignKey(
        Feature, on_delete=models.CASCADE, related_name="platform_availability"
    )
    platform = models.CharField(max_length=16, choices=Platform.choices)
    is_available = models.BooleanField(default=True)
    degradation_note = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Shown in the builder when the feature works, but differently."),
    )

    class Meta:
        db_table = "feature_platform_availability"
        constraints = [
            models.UniqueConstraint(
                fields=["feature", "platform"], name="feature_platform_uniq"
            )
        ]

    def __str__(self) -> str:
        return f"{self.feature.slug}@{self.platform}"
