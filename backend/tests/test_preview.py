"""The pre-payment preview and the adapter degradation ladder.

The preview doubles as the proof that the core is genuinely channel-independent: it
renders the same `Reply` objects the runtime will, through a third adapter.
"""

from __future__ import annotations

import pytest

from apps.platforms.bale.adapter import BALE_CAPABILITIES
from apps.platforms.base import ButtonLayout, Capabilities, Choice, RenderContext, Reply
from apps.platforms.preview.messages import translate
from apps.platforms.preview.service import build_preview
from apps.platforms.rendering import render_with_capabilities
from apps.platforms.telegram.adapter import TELEGRAM_CAPABILITIES


def ctx(locale: str = "en") -> RenderContext:
    return RenderContext(locale=locale, business_name="Demo Clinic", translate=translate)


def caps(**overrides) -> Capabilities:
    base = dict(
        inline_keyboards=True,
        reply_keyboards=True,
        max_buttons_per_row=3,
        max_buttons_total=100,
        media_groups=True,
        message_editing=True,
        web_app=True,
        file_uploads=True,
        max_text_length=4096,
        verified=True,
    )
    base.update(overrides)
    return Capabilities(**base)


MENU = Reply(
    text_key="bot.welcome",
    params={"business": "Demo Clinic"},
    choices=[
        Choice(label_key="menu.about", value="a"),
        Choice(label_key="menu.contact", value="b"),
        Choice(label_key="menu.faq", value="c"),
        Choice(label_key="menu.book", value="d"),
    ],
)


class TestDegradationLadder:
    def test_inline_keyboards_are_used_when_available(self):
        assert render_with_capabilities(MENU, ctx(), caps()).layout == ButtonLayout.INLINE

    def test_falls_back_to_a_reply_keyboard(self):
        message = render_with_capabilities(MENU, ctx(), caps(inline_keyboards=False))
        assert message.layout == ButtonLayout.REPLY
        assert message.buttons
        assert any("reply keyboard" in note for note in message.notes)

    def test_falls_back_to_a_numbered_list(self):
        """A platform with no buttons at all must still be usable."""
        message = render_with_capabilities(
            MENU, ctx(), caps(inline_keyboards=False, reply_keyboards=False)
        )
        assert message.layout == ButtonLayout.NUMBERED
        assert message.buttons == []
        assert "1. About us" in message.text
        assert "4. Book an appointment" in message.text

    def test_rows_respect_the_platform_width(self):
        message = render_with_capabilities(MENU, ctx(), caps(max_buttons_per_row=2))
        assert [len(row) for row in message.buttons] == [2, 2]

    def test_button_count_is_capped(self):
        message = render_with_capabilities(MENU, ctx(), caps(max_buttons_total=2))
        assert sum(len(row) for row in message.buttons) == 2
        assert any("pagination" in note for note in message.notes)

    def test_long_text_is_trimmed_and_reported(self):
        message = render_with_capabilities(MENU, ctx(), caps(max_text_length=20))
        assert len(message.text) <= 20
        assert any("trimmed" in note for note in message.notes)

    def test_no_choices_means_no_buttons(self):
        message = render_with_capabilities(Reply(text_key="bot.business.about"), ctx(), caps())
        assert message.layout == ButtonLayout.NONE
        assert message.buttons == []

    def test_a_missing_translation_shows_the_key_not_a_blank(self):
        message = render_with_capabilities(Reply(text_key="bot.nonexistent"), ctx(), caps())
        assert message.text == "bot.nonexistent"


class TestLocalisedRendering:
    def test_persian_copy_is_used(self):
        message = render_with_capabilities(MENU, ctx("fa"), caps())
        assert "خوش آمدید" in message.text

    def test_button_labels_are_translated(self):
        message = render_with_capabilities(MENU, ctx("fa"), caps())
        assert "درباره ما" in message.buttons[0]

    def test_the_business_name_is_interpolated(self):
        message = render_with_capabilities(MENU, ctx(), caps())
        assert "Demo Clinic" in message.text


@pytest.mark.django_db
class TestPreviewService:
    def test_it_renders_one_preview_per_platform(self, catalogue):
        previews = build_preview(
            feature_slugs=["business_profile", "faq"],
            platforms=["telegram", "bale"],
            business_name="Demo Clinic",
        )
        assert [p.platform for p in previews] == ["telegram", "bale"]

    def test_the_main_menu_is_built_from_the_selected_features(self, catalogue):
        previews = build_preview(
            feature_slugs=["business_profile", "faq", "appointment"],
            platforms=["telegram"],
            business_name="Demo Clinic",
        )
        menu = previews[0].screens[0]
        labels = [label for row in menu.message["buttons"] for label in row]
        assert "Book an appointment" in labels
        assert "FAQ" in labels

    def test_unselected_features_do_not_appear_in_the_menu(self, catalogue):
        previews = build_preview(
            feature_slugs=["business_profile"],
            platforms=["telegram"],
            business_name="Demo Clinic",
        )
        labels = [
            label for row in previews[0].screens[0].message["buttons"] for label in row
        ]
        assert "Book an appointment" not in labels

    def test_each_feature_contributes_its_sample_interaction(self, catalogue):
        previews = build_preview(
            feature_slugs=["business_profile", "appointment"],
            platforms=["telegram"],
            business_name="Demo Clinic",
        )
        keys = [screen.key for screen in previews[0].screens]
        assert any(key.startswith("appointment:") for key in keys)

    def test_bale_previews_are_flagged_as_provisional(self, catalogue):
        """Honesty about R-02: do not imply the mock-up is authoritative."""
        previews = build_preview(
            feature_slugs=["business_profile"],
            platforms=["bale"],
            business_name="Demo Clinic",
        )
        assert previews[0].capabilities_verified is False
        assert any("provisional" in warning for warning in previews[0].warnings)

    def test_telegram_capabilities_are_verified(self, catalogue):
        previews = build_preview(
            feature_slugs=["business_profile"],
            platforms=["telegram"],
            business_name="Demo Clinic",
        )
        assert previews[0].capabilities_verified is True

    def test_the_preview_is_localised(self, catalogue):
        previews = build_preview(
            feature_slugs=["business_profile"],
            platforms=["telegram"],
            business_name="کلینیک نمونه",
            locale="fa",
        )
        assert "خوش آمدید" in previews[0].screens[0].message["text"]


class TestDeclaredCapabilities:
    def test_bale_is_not_claimed_as_verified(self):
        assert BALE_CAPABILITIES.verified is False

    def test_telegram_is_verified(self):
        assert TELEGRAM_CAPABILITIES.verified is True

    def test_bale_does_not_claim_media_groups(self):
        """Claiming an unconfirmed capability would sell a silently broken feature."""
        assert BALE_CAPABILITIES.media_groups is False
