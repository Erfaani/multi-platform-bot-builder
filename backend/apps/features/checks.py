"""Startup checks keeping the catalogue and the code in step.

Drift here is silent and expensive: a customer buys a feature the runtime cannot route,
payment succeeds, provisioning succeeds, and the bot is simply missing a menu. So it is
a hard startup failure, not a warning (ARCHITECTURE.md §5).
"""

from __future__ import annotations

from django.core.checks import Error, Warning, register

FEATURE_TAG = "features"


@register(FEATURE_TAG)
def check_manifest_catalogue_agreement(app_configs, **kwargs) -> list:
    from django.db import OperationalError, ProgrammingError

    from apps.features.manifests import FeatureCategory
    from apps.features.models import Feature
    from apps.features.registry import all_manifests

    problems: list = []
    manifests = all_manifests()

    for slug, manifest in manifests.items():
        if manifest.category not in FeatureCategory.ALL:
            problems.append(
                Error(
                    f"Feature {slug!r} declares unknown category {manifest.category!r}.",
                    id="features.E003",
                )
            )
        for dependency in manifest.requires:
            if dependency not in manifests:
                problems.append(
                    Error(
                        f"Feature {slug!r} requires {dependency!r}, which has no manifest.",
                        id="features.E004",
                    )
                )

    try:
        active_slugs = set(Feature.objects.filter(is_active=True).values_list("slug", flat=True))
    except (OperationalError, ProgrammingError):
        # Before the first migrate there is no table; that is not a configuration error.
        return problems

    for slug in sorted(active_slugs - set(manifests)):
        problems.append(
            Error(
                f"Active feature {slug!r} is sellable but has no manifest, so the runtime "
                "cannot route it. Add a manifest or deactivate the feature.",
                id="features.E001",
            )
        )

    for slug in sorted(set(manifests) - active_slugs):
        problems.append(
            Warning(
                f"Feature {slug!r} has a manifest but no active catalogue row, so it "
                "cannot be sold. Run `seed_catalogue` or activate it in the admin.",
                id="features.W002",
            )
        )

    return problems
