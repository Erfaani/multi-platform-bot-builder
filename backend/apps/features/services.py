"""Feature availability.

Two independent gates, and a feature must clear both:

1. **Capability** — does the platform technically support what the manifest needs?
   Derived from the adapter, so it cannot go stale relative to the code.
2. **Policy** — is operations willing to sell it there? A database row, so a limitation
   found in production can be acted on without a deploy.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.features.models import Feature, FeaturePlatformAvailability
from apps.features.registry import all_manifests
from apps.platforms.registry import capabilities_for, sellable_adapters


@dataclass(frozen=True, slots=True)
class Availability:
    feature_slug: str
    platform: str
    is_available: bool
    reason: str = ""
    note: str = ""


def availability_matrix(platforms: list[str] | None = None) -> dict[str, list[Availability]]:
    """Availability of every active feature on every requested platform."""
    platforms = platforms or list(sellable_adapters())
    manifests = all_manifests()

    policy = {
        (row.feature.slug, row.platform): row
        for row in FeaturePlatformAvailability.objects.select_related("feature")
    }

    matrix: dict[str, list[Availability]] = {}
    for feature in Feature.objects.filter(is_active=True):
        manifest = manifests.get(feature.slug)
        entries: list[Availability] = []

        for platform in platforms:
            if manifest is None:
                entries.append(
                    Availability(feature.slug, platform, False, reason="no_manifest")
                )
                continue

            missing = manifest.platform_requirements.unmet_on(capabilities_for(platform))
            if missing:
                entries.append(
                    Availability(
                        feature.slug,
                        platform,
                        False,
                        reason="unsupported_capability",
                        note=f"Requires {', '.join(missing)}.",
                    )
                )
                continue

            row = policy.get((feature.slug, platform))
            if row is not None and not row.is_available:
                entries.append(
                    Availability(
                        feature.slug,
                        platform,
                        False,
                        reason="withdrawn",
                        note=row.degradation_note,
                    )
                )
                continue

            entries.append(
                Availability(
                    feature.slug,
                    platform,
                    True,
                    note=row.degradation_note if row else "",
                )
            )

        matrix[feature.slug] = entries

    return matrix


def unavailable_selections(feature_slugs: list[str], platforms: list[str]) -> list[Availability]:
    """The subset of a selection that cannot be delivered on the chosen platforms.

    Called before a quote is priced: selling something undeliverable is worse than
    refusing the sale.
    """
    matrix = availability_matrix(platforms)
    problems: list[Availability] = []

    for slug in feature_slugs:
        for entry in matrix.get(slug, []):
            if not entry.is_available:
                problems.append(entry)

    return problems
