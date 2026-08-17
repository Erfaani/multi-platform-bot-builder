"""The bot's command list, assembled from its enabled features.

Commands come from feature manifests, so a bot only advertises what it can actually do —
a `/book` command on a bot without the appointment feature is a support ticket waiting to
happen.
"""

from __future__ import annotations

from apps.platforms.preview.messages import translate

#: Always present, whatever the customer bought.
BASE_COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "command.start"),
    ("menu", "command.menu"),
    ("help", "command.help"),
    ("language", "command.language"),
)

#: Feature slug → (command, description key). Only added when the feature is enabled.
FEATURE_COMMANDS: dict[str, tuple[str, str]] = {
    "appointment": ("book", "command.book"),
    "faq": ("faq", "command.faq"),
    "product_catalog": ("catalog", "command.catalog"),
    "cart_orders": ("cart", "command.cart"),
    "table_reservation": ("reserve", "command.reserve"),
    "contact": ("contact", "command.contact"),
    "ai_assistant": ("ask", "command.ask"),
}

COMMAND_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "command.start": {"en": "Start the bot", "fa": "شروع"},
    "command.menu": {"en": "Show the main menu", "fa": "منوی اصلی"},
    "command.help": {"en": "How to use this bot", "fa": "راهنما"},
    "command.language": {"en": "Change language", "fa": "تغییر زبان"},
    "command.book": {"en": "Book an appointment", "fa": "رزرو نوبت"},
    "command.faq": {"en": "Frequently asked questions", "fa": "سوالات متداول"},
    "command.catalog": {"en": "Browse products", "fa": "مشاهده محصولات"},
    "command.cart": {"en": "View your cart", "fa": "سبد خرید"},
    "command.reserve": {"en": "Reserve a table", "fa": "رزرو میز"},
    "command.contact": {"en": "Contact us", "fa": "تماس با ما"},
    "command.ask": {"en": "Ask a question", "fa": "پرسش از دستیار"},
}


def _describe(key: str, locale: str) -> str:
    entry = COMMAND_DESCRIPTIONS.get(key)
    if entry is None:
        return translate(key, locale=locale)
    return entry.get(locale) or entry.get(locale.split("-")[0]) or entry["en"]


def command_list_for(bot, locale: str) -> list[dict]:
    """Build the `setMyCommands` payload for one locale."""
    enabled = set(
        bot.bot_features.filter(is_enabled=True).values_list("feature__slug", flat=True)
    )

    commands = [
        {"command": name, "description": _describe(key, locale)}
        for name, key in BASE_COMMANDS
    ]
    for slug, (name, key) in FEATURE_COMMANDS.items():
        if slug in enabled:
            commands.append({"command": name, "description": _describe(key, locale)})

    # Telegram caps the list at 100; we are nowhere near, but be explicit.
    return commands[:100]
