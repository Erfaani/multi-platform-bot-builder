"""Manifest discovery.

Every installed app may expose a `manifest.py` declaring one or more
:class:`FeatureManifest`. They are collected once at app-ready and indexed by slug.
"""

from __future__ import annotations

import importlib
from functools import lru_cache

from django.apps import apps as django_apps

from apps.features.manifests import FeatureManifest

_MANIFEST_MODULE = "manifest"


@lru_cache(maxsize=1)
def all_manifests() -> dict[str, FeatureManifest]:
    """Discover manifests across installed apps, keyed by slug."""
    found: dict[str, FeatureManifest] = {}

    for app_config in django_apps.get_app_configs():
        try:
            module = importlib.import_module(f"{app_config.name}.{_MANIFEST_MODULE}")
        except ModuleNotFoundError:
            continue

        for manifest in getattr(module, "MANIFESTS", ()):
            if manifest.slug in found:
                raise ImproperlyConfiguredManifest(
                    f"Duplicate feature slug {manifest.slug!r} "
                    f"(second declaration in {app_config.name})."
                )
            found[manifest.slug] = manifest

    return found


class ImproperlyConfiguredManifest(Exception):
    """Two apps claimed the same feature slug."""


def get_manifest(slug: str) -> FeatureManifest:
    try:
        return all_manifests()[slug]
    except KeyError as exc:
        raise LookupError(f"No feature manifest registered for {slug!r}.") from exc


def manifests_for(slugs) -> list[FeatureManifest]:
    registry = all_manifests()
    return [registry[slug] for slug in slugs if slug in registry]


def always_on_slugs() -> tuple[str, ...]:
    return tuple(
        slug for slug, manifest in all_manifests().items() if manifest.always_on
    )


def resolve_dependencies(slugs) -> tuple[list[str], list[str]]:
    """Expand ``slugs`` with everything they require.

    Returns ``(resolved, added)``. The builder shows ``added`` so a customer
    understands why FAQ appeared when they picked the AI assistant.
    """
    registry = all_manifests()
    resolved: list[str] = []
    added: list[str] = []

    def visit(slug: str, is_root: bool) -> None:
        if slug in resolved or slug not in registry:
            return
        for dependency in registry[slug].requires:
            visit(dependency, False)
        resolved.append(slug)
        if not is_root:
            added.append(slug)

    for slug in slugs:
        visit(slug, True)

    for slug in always_on_slugs():
        if slug not in resolved:
            resolved.insert(0, slug)

    return resolved, added


def clear_cache() -> None:
    all_manifests.cache_clear()
