"""Database-backed translations for dynamic content (I18N.md §1).

``gettext`` covers strings that ship with the code. Template names, feature
descriptions, payment instructions and a customer's own welcome message are *data*,
and they live here.
"""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import TimeStampedModel


class Translation(TimeStampedModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    field = models.CharField(max_length=64)
    locale = models.CharField(max_length=8)
    value = models.TextField(blank=True)

    class Meta:
        db_table = "translation"
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id", "field", "locale"],
                name="translation_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=["content_type", "object_id", "locale"], name="translation_lookup_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.content_type_id}#{self.object_id}.{self.field}[{self.locale}]"
