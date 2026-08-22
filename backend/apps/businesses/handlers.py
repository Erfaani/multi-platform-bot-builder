"""Core feature handlers (spec §11 "Core").

Every handler here obeys the contract: takes an event, a session and a context; returns
a `HandlerResult`; emits translation keys, never literal text; sends nothing itself.

Because of that they are testable with no network, no database and no bot — and the
preview adapter renders these exact objects.
"""

from __future__ import annotations

from apps.bot_runtime.handlers import HandlerResult, command, route
from apps.platforms.base import Choice, Reply
from apps.features.registry import manifests_for

WELCOME_KEY = "bot.welcome"


def _menu_choices(ctx) -> list[Choice]:
    """Main menu, assembled from the manifests of the features this bot has."""
    entries = sorted(
        (entry for manifest in manifests_for(ctx.enabled_features) for entry in manifest.menu),
        key=lambda entry: entry.sort_order,
    )
    return [Choice(label_key=entry.label_key, value=entry.route) for entry in entries]


def _business(ctx) -> dict:
    return ctx.business


@route("core:menu")
@command("menu")
@command("start")
def main_menu(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    """Welcome message plus the main menu.

    A customer-written welcome overrides the default; otherwise the localized template
    greeting is used, so a bot never opens with an empty message.
    """
    session.reset()

    if ctx.welcome_message:
        reply = Reply(
            text_key="bot.welcome.custom",
            params={"text": ctx.welcome_message},
            choices=_menu_choices(ctx),
        )
    else:
        reply = Reply(
            text_key=WELCOME_KEY,
            params={"business": ctx.bot_name},
            choices=_menu_choices(ctx),
        )

    return HandlerResult(reply=reply, next_state="IDLE")


@command("help")
def help_command(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    return HandlerResult(
        reply=Reply(
            text_key="bot.help",
            params={"business": ctx.bot_name},
            choices=_menu_choices(ctx),
        ),
        next_state="IDLE",
    )


@command("language")
@route("core:language")
def language_command(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    """Offer a language switch. The choice is stored on the session, so it survives."""
    from django.conf import settings

    if value in settings.ACTIVE_LOCALES:
        session.locale = value
        return HandlerResult(
            reply=Reply(text_key="bot.language.changed", choices=_menu_choices(ctx)),
            next_state="IDLE",
        )

    return HandlerResult(
        reply=Reply(
            text_key="bot.language.prompt",
            choices=[
                Choice(label_key=f"bot.language.{code}", value=f"core:language.{code}")
                for code in settings.ACTIVE_LOCALES
            ],
        ),
        next_state="IDLE",
    )


@route("core:open_app")
def open_app(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    """Launch the Mini App (Phase 10.5). `Capabilities.web_app` is false for Bale
    (`apps.platforms.bale.adapter`), so this degrades to an explanatory message there
    rather than a button nobody can tap."""
    if ctx.platform != "telegram":
        return HandlerResult(
            reply=Reply(text_key="bot.miniapp.unavailable", choices=_menu_choices(ctx)),
            next_state="IDLE",
        )

    from django.conf import settings

    url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/{locale}/miniapp/{ctx.instance_public_id}"
    return HandlerResult(
        reply=Reply(
            text_key="bot.miniapp.launch",
            choices=[Choice(label_key="menu.open_app", value="core:open_app.go", web_app_url=url)],
        ),
        next_state="IDLE",
    )


@route("business:about")
def about(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    business = _business(ctx)
    description = business.get("description") or ""
    return HandlerResult(
        reply=Reply(
            text_key="bot.business.about.custom" if description else "bot.business.about",
            params={"business": ctx.bot_name, "description": description},
            choices=_menu_choices(ctx),
        ),
        next_state="IDLE",
    )


@route("business:contact")
@command("contact")
def contact(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    business = _business(ctx)
    return HandlerResult(
        reply=Reply(
            text_key="bot.business.contact.custom",
            params={
                "phone": business.get("phone") or "—",
                "email": business.get("email") or "—",
            },
            choices=_menu_choices(ctx),
        ),
        next_state="IDLE",
    )


@route("business:location")
def location(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    business = _business(ctx)
    return HandlerResult(
        reply=Reply(
            text_key="bot.business.location.custom",
            params={"address": business.get("address") or "—"},
            choices=_menu_choices(ctx),
        ),
        next_state="IDLE",
    )


@route("business:hours")
def working_hours(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    """Opening hours.

    Real per-day rows arrive with the appointment module in Phase 7; until then this
    renders whatever the customer entered in the builder.
    """
    business = _business(ctx)
    hours = business.get("working_hours") or ""
    return HandlerResult(
        reply=Reply(
            text_key="bot.business.hours.custom" if hours else "bot.business.hours",
            params={"hours": hours},
            choices=_menu_choices(ctx),
        ),
        next_state="IDLE",
    )


@route("faq:list")
@command("faq")
def faq_list(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    """FAQ entries for this bot, most relevant first."""
    from apps.businesses.models import FaqEntry

    entries = list(
        FaqEntry.objects.filter(bot_id=ctx.bot_id, is_active=True).order_by("sort_order")[:10]
    )

    if not entries:
        return HandlerResult(
            reply=Reply(text_key="bot.faq.empty", choices=_menu_choices(ctx)), next_state="IDLE"
        )

    if value:
        entry = next((e for e in entries if str(e.pk) == value), None)
        if entry is not None:
            return HandlerResult(
                reply=Reply(
                    text_key="bot.faq.answer",
                    params={"question": entry.question, "answer": entry.answer},
                    choices=_menu_choices(ctx),
                ),
                next_state="IDLE",
            )

    return HandlerResult(
        reply=Reply(
            text_key="bot.faq.prompt",
            choices=[
                Choice(label_key=f"literal:{entry.question}", value=f"faq:list.{entry.pk}")
                for entry in entries
            ],
        ),
        next_state="IDLE",
    )
