"""Builds the pre-payment bot preview (spec §48).

Composes screens from the selected features' manifests and renders them through an
adapter, **per platform**. Rendering per platform matters: showing a Telegram mock-up to
someone buying a Bale bot is a promise the product may not keep, and the difference is
exactly what a customer needs to see before paying.

Nothing here talks to a real bot. The preview must never activate anything.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from apps.features.manifests import FeatureManifest
from apps.features.registry import manifests_for
from apps.platforms.base import Choice, RenderContext, Reply
from apps.platforms.preview.adapter import PreviewAdapter
from apps.platforms.preview.messages import translate
from apps.platforms.registry import capabilities_for, get_adapter

_adapter = PreviewAdapter()


@dataclass(slots=True)
class PreviewScreen:
    key: str
    title: str
    user_says: str | None
    message: dict


@dataclass(slots=True)
class PlatformPreview:
    platform: str
    display_name: str
    capabilities_verified: bool
    screens: list[PreviewScreen] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _main_menu_reply(manifests: list[FeatureManifest], business_name: str) -> Reply:
    entries = sorted(
        (entry for manifest in manifests for entry in manifest.menu),
        key=lambda entry: entry.sort_order,
    )
    return Reply(
        text_key="bot.welcome",
        params={"business": business_name},
        choices=[Choice(label_key=entry.label_key, value=entry.route) for entry in entries],
    )


def build_preview(
    *,
    feature_slugs: list[str],
    platforms: list[str],
    business_name: str,
    locale: str = "en",
) -> list[PlatformPreview]:
    manifests = manifests_for(feature_slugs)
    ctx = RenderContext(locale=locale, business_name=business_name, translate=translate)

    previews: list[PlatformPreview] = []

    for platform in platforms:
        adapter = get_adapter(platform)
        capabilities = capabilities_for(platform)

        preview = PlatformPreview(
            platform=platform,
            display_name=getattr(adapter, "display_name", platform.title()),
            capabilities_verified=capabilities.verified,
        )

        if not capabilities.verified:
            # Say so plainly rather than implying the mock-up is authoritative.
            preview.warnings.append(
                f"{preview.display_name} capabilities are provisional and pending "
                "verification; the live layout may differ slightly."
            )

        # 1. Welcome + main menu, assembled from every selected feature's menu entries.
        menu_reply = _main_menu_reply(manifests, business_name)
        rendered = _adapter.render_as(menu_reply, ctx, capabilities)
        preview.screens.append(
            PreviewScreen(
                key="main_menu",
                title=translate("preview.step.main_menu", locale=locale),
                user_says="/start",
                message=PreviewAdapter.to_json(rendered),
            )
        )

        # 2. Each feature's own sample interaction.
        for manifest in manifests:
            for index, step in enumerate(manifest.preview):
                rendered = _adapter.render_as(
                    _with_business(step.reply, business_name), ctx, capabilities
                )
                preview.screens.append(
                    PreviewScreen(
                        key=f"{manifest.slug}:{index}",
                        title=translate(step.title_key, locale=locale),
                        user_says=(
                            translate(step.user_says_key, locale=locale)
                            if step.user_says_key
                            else None
                        ),
                        message=PreviewAdapter.to_json(rendered),
                    )
                )

        # Surface degradation once per platform rather than on every screen.
        notes = {
            note
            for screen in preview.screens
            for note in screen.message.get("notes", [])
        }
        preview.warnings.extend(sorted(notes))

        previews.append(preview)

    return previews


def _with_business(reply: Reply, business_name: str) -> Reply:
    """Substitute the placeholder a manifest used for the business name."""
    if not reply.params:
        return reply
    params = {
        key: (business_name if value == "{business_name}" else value)
        for key, value in reply.params.items()
    }
    return Reply(
        text_key=reply.text_key,
        params=params,
        choices=reply.choices,
        attachments=reply.attachments,
        expects=reply.expects,
    )


def preview_to_json(previews: list[PlatformPreview]) -> list[dict]:
    return [asdict(preview) for preview in previews]
