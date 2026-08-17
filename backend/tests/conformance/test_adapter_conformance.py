"""Adapter conformance suite (BOT_RUNTIME.md §8).

Every adapter runs the same scenarios. This is what keeps the channel-independence claim
honest: if a change makes the core assume Telegram's shape, a Bale case fails here rather
than in front of a customer.

No live network — adapters are exercised through recorded payloads and the fake transport.
"""

from __future__ import annotations

import pytest

from apps.platforms.bale.adapter import BaleAdapter
from apps.platforms.base import ButtonLayout, Capabilities, Choice, RenderContext, Reply
from apps.platforms.preview.adapter import PreviewAdapter
from apps.platforms.preview.messages import translate
from apps.platforms.telegram.adapter import TelegramAdapter

INSTANCE = "11111111-2222-3333-4444-555555555555"

#: Every adapter that must behave. `preview` is included deliberately — it is a real
#: adapter, not a mock, so it keeps the contract honest too.
ADAPTERS = [TelegramAdapter(), BaleAdapter(), PreviewAdapter()]
PARSING_ADAPTERS = [TelegramAdapter(), BaleAdapter()]

ADAPTER_IDS = [a.slug for a in ADAPTERS]
PARSING_IDS = [a.slug for a in PARSING_ADAPTERS]


def ctx(locale: str = "en") -> RenderContext:
    return RenderContext(locale=locale, business_name="Demo Clinic", translate=translate)


MENU = Reply(
    text_key="bot.welcome",
    params={"business": "Demo Clinic"},
    choices=[
        Choice(label_key="menu.about", value="business:about"),
        Choice(label_key="menu.contact", value="business:contact"),
        Choice(label_key="menu.faq", value="faq:list"),
    ],
)


def text_update(text: str = "hello") -> dict:
    """A message update in the shape both platforms use."""
    return {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "text": text,
            "chat": {"id": 4242},
            "from": {"id": 77, "first_name": "Sara", "username": "sara", "language_code": "fa"},
        },
    }


def callback_update(data: str = "v1.sig.core:menu.") -> dict:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb-1",
            "data": data,
            "from": {"id": 77, "first_name": "Sara"},
            "message": {"message_id": 10, "chat": {"id": 4242}},
        },
    }


@pytest.mark.parametrize("adapter", PARSING_ADAPTERS, ids=PARSING_IDS)
class TestParsing:
    def test_a_command_is_identified(self, adapter):
        event = adapter.parse(text_update("/start"), INSTANCE)
        assert event.kind == "command"
        assert event.text == "/start"

    def test_plain_text_is_a_message(self, adapter):
        assert adapter.parse(text_update("hello"), INSTANCE).kind == "message"

    def test_chat_and_user_are_strings(self, adapter):
        """The core keys sessions on these; an int on one platform and a string on the
        other would silently create two sessions for one user."""
        event = adapter.parse(text_update(), INSTANCE)
        assert isinstance(event.chat_ref, str)
        assert isinstance(event.user_ref, str)
        assert event.chat_ref == "4242"
        assert event.user_ref == "77"

    def test_the_platform_is_reported(self, adapter):
        assert adapter.parse(text_update(), INSTANCE).platform == adapter.slug

    def test_the_instance_is_carried_through(self, adapter):
        assert adapter.parse(text_update(), INSTANCE).instance_public_id == INSTANCE

    def test_a_callback_is_identified(self, adapter):
        event = adapter.parse(callback_update(), INSTANCE)
        assert event.kind == "callback"
        assert event.payload["data"] == "v1.sig.core:menu."

    def test_the_display_name_is_assembled(self, adapter):
        assert adapter.parse(text_update(), INSTANCE).user_display_name == "Sara"

    def test_an_empty_update_does_not_explode(self, adapter):
        """Platforms send update types we do not handle; that is not a crash."""
        event = adapter.parse({"update_id": 9}, INSTANCE)
        assert event.kind == "unknown"
        assert event.chat_ref == ""

    def test_an_unknown_message_type_is_unknown_not_a_crash(self, adapter):
        raw = {
            "update_id": 3,
            "message": {"message_id": 1, "chat": {"id": 1}, "from": {"id": 2}, "sticker": {}},
        }
        assert adapter.parse(raw, INSTANCE).kind == "unknown"


@pytest.mark.parametrize("adapter", ADAPTERS, ids=ADAPTER_IDS)
class TestRendering:
    def test_a_reply_renders_to_text(self, adapter):
        message = adapter.render(MENU, ctx())
        assert "Demo Clinic" in message.text

    def test_choices_become_buttons_or_a_list(self, adapter):
        """However the platform does it, all three options must reach the user."""
        message = adapter.render(MENU, ctx())
        if message.layout == ButtonLayout.NUMBERED:
            for label in ("About us", "Contact", "FAQ"):
                assert label in message.text
        else:
            labels = [label for row in message.buttons for label in row]
            assert labels == ["About us", "Contact", "FAQ"]

    def test_no_reply_has_no_buttons(self, adapter):
        message = adapter.render(Reply(text_key="bot.business.about"), ctx())
        assert message.buttons == []
        assert message.layout == ButtonLayout.NONE

    def test_rendering_is_localised(self, adapter):
        assert "خوش آمدید" in adapter.render(MENU, ctx("fa")).text

    def test_text_respects_the_platform_limit(self, adapter):
        message = adapter.render(MENU, ctx())
        assert len(message.text) <= adapter.capabilities.max_text_length

    def test_rows_respect_the_platform_width(self, adapter):
        message = adapter.render(MENU, ctx())
        for row in message.buttons:
            assert len(row) <= adapter.capabilities.max_buttons_per_row

    def test_a_missing_key_renders_the_key_not_a_blank(self, adapter):
        """A blank message is indistinguishable from a broken bot."""
        assert adapter.render(Reply(text_key="bot.does.not.exist"), ctx()).text == (
            "bot.does.not.exist"
        )

    def test_customer_text_passes_through_literally(self, adapter):
        message = adapter.render(Reply(text_key="literal:Dr Ahmadi's clinic"), ctx())
        assert message.text == "Dr Ahmadi's clinic"


@pytest.mark.parametrize("adapter", ADAPTERS, ids=ADAPTER_IDS)
class TestCapabilityHonesty:
    def test_capabilities_are_declared(self, adapter):
        assert isinstance(adapter.capabilities, Capabilities)

    def test_limits_are_positive(self, adapter):
        assert adapter.capabilities.max_text_length > 0
        assert adapter.capabilities.max_buttons_per_row > 0

    def test_at_least_one_way_to_offer_choices(self, adapter):
        """Buttons or a numbered list — but the ladder must terminate somewhere."""
        message = adapter.render(MENU, ctx())
        assert message.buttons or message.layout == ButtonLayout.NUMBERED

    def test_unverified_adapters_say_so(self, adapter):
        """Bale ships `verified=False` until `probe_bale` is run (R-02).

        This test does not demand verification — it demands honesty about it.
        """
        if adapter.slug == "bale":
            assert adapter.capabilities.verified is False, (
                "Bale claims verified capabilities. Run `manage.py probe_bale` and "
                "record the results in BALE.md before setting this."
            )


class TestNoInheritanceBetweenChannels:
    def test_bale_does_not_inherit_from_telegram(self):
        """Inheritance would silently borrow behaviour Bale may not have (R-02)."""
        assert not issubclass(BaleAdapter, TelegramAdapter)
        assert not issubclass(TelegramAdapter, BaleAdapter)

    def test_the_adapters_are_independent_implementations(self):
        assert BaleAdapter.parse is not TelegramAdapter.parse

    def test_both_report_distinct_slugs(self):
        assert TelegramAdapter().slug != BaleAdapter().slug


class TestDegradationLadder:
    """The ladder is what makes a missing capability a presentation difference rather
    than a broken feature."""

    def _caps(self, **overrides) -> Capabilities:
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

    def test_every_rung_still_delivers_all_options(self):
        from apps.platforms.rendering import render_with_capabilities

        ladders = [
            self._caps(),
            self._caps(inline_keyboards=False),
            self._caps(inline_keyboards=False, reply_keyboards=False),
        ]
        for capabilities in ladders:
            message = render_with_capabilities(MENU, ctx(), capabilities)
            rendered = " ".join(
                [message.text] + [label for row in message.buttons for label in row]
            )
            for label in ("About us", "Contact", "FAQ"):
                assert label in rendered, f"lost {label!r} at {capabilities}"
