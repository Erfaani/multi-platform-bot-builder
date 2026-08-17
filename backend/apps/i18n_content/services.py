"""Translation resolution.

Resolution chain (I18N.md §1), first hit wins::

    requested locale → owner default locale → platform default → source value

Falling back beats rendering an empty string: an untranslated business name is far
better than a blank one.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import translation as django_translation

from apps.i18n_content.models import Translation


def set_translations(obj, field: str, values: dict[str, str]) -> None:
    """Upsert ``{locale: value}`` for one field of one object."""
    content_type = ContentType.objects.get_for_model(obj)
    for locale, value in values.items():
        Translation.objects.update_or_create(
            content_type=content_type,
            object_id=obj.pk,
            field=field,
            locale=locale,
            defaults={"value": value},
        )


def get_translations(obj, *fields: str) -> dict[str, dict[str, str]]:
    """All stored translations for ``obj`` as ``{field: {locale: value}}``."""
    content_type = ContentType.objects.get_for_model(obj)
    queryset = Translation.objects.filter(content_type=content_type, object_id=obj.pk)
    if fields:
        queryset = queryset.filter(field__in=fields)

    result: dict[str, dict[str, str]] = {}
    for row in queryset:
        result.setdefault(row.field, {})[row.locale] = row.value
    return result


def translate(
    obj,
    field: str,
    *,
    locale: str | None = None,
    owner_default_locale: str | None = None,
    source: str | None = None,
) -> str:
    """Resolve one field for one locale, walking the fallback chain."""
    locale = locale or django_translation.get_language() or settings.LANGUAGE_CODE
    stored = get_translations(obj, field).get(field, {})

    for candidate in (locale, locale.split("-")[0], owner_default_locale, settings.LANGUAGE_CODE):
        if candidate and stored.get(candidate):
            return stored[candidate]

    if source is not None:
        return source
    return next((value for value in stored.values() if value), "")
