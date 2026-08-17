"""Lead capture and feedback (spec's CRM module).

`contact_request` and `consultation_request` are the first genuinely free-text flows in
this codebase — every earlier feature (FAQ, appointments) stayed enumerable and never
touched `session.state`. These two must: there is no menu of possible messages a customer
might send. Each is two steps — ask, then whatever comes back is the answer — and each
step re-checks `event.kind` for a stray command (the customer typing `/menu` mid-flow)
so the flow can bail out to the main menu instead of capturing "/menu" as their message.

`feedback` stays enumerable (a 1–5 star tap) and needs none of this — see the manifest's
own preview, which shows only the rating step.
"""

from __future__ import annotations

from apps.bot_runtime.handlers import HandlerResult, command, route, state
from apps.platforms.base import Choice, Reply

from apps.crm import services
from apps.crm.models import LeadSource

PHONE_MIN_DIGITS = 7
PHONE_MAX_DIGITS = 15


def _menu_choices(ctx) -> list[Choice]:
    from apps.features.registry import manifests_for

    entries = sorted(
        (entry for manifest in manifests_for(ctx.enabled_features) for entry in manifest.menu),
        key=lambda entry: entry.sort_order,
    )
    return [Choice(label_key=entry.label_key, value=entry.route) for entry in entries]


def _main_menu(ctx) -> HandlerResult:
    return HandlerResult(
        reply=Reply(text_key="bot.welcome", params={"business": ctx.bot_name}, choices=_menu_choices(ctx)),
        next_state="IDLE",
    )


def _bot_and_contact(ctx, event):
    from apps.bots.models import Bot
    from apps.bot_runtime.models import BusinessContact

    bot = Bot.objects.select_related("tenant").get(pk=ctx.bot_id)
    contact = BusinessContact.objects.get(
        bot_id=ctx.bot_id, platform=ctx.platform, platform_user_id=event.user_ref
    )
    return bot, contact


def _looks_like_phone(text: str) -> bool:
    digits = "".join(ch for ch in text if ch.isdigit())
    return PHONE_MIN_DIGITS <= len(digits) <= PHONE_MAX_DIGITS


# --------------------------------------------------------------------------- contact request


@route("crm:contact")
@command("contactus")
def start_contact_request(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    session.reset()
    return HandlerResult(
        reply=Reply(text_key="bot.crm.ask_message", expects="text"),
        next_state="crm:awaiting_message",
    )


@state("crm:awaiting_message")
def capture_message(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if event.kind == "command":
        session.reset()
        return _main_menu(ctx)

    text = (event.text or "").strip()
    if not text:
        return HandlerResult(
            reply=Reply(text_key="bot.crm.ask_message", expects="text"),
            next_state="crm:awaiting_message",
        )

    bot, contact = _bot_and_contact(ctx, event)
    services.create_lead(bot=bot, contact=contact, source=LeadSource.CONTACT_FORM, message=text)

    session.reset()
    return HandlerResult(
        reply=Reply(text_key="bot.crm.message_received", choices=_menu_choices(ctx)), next_state="IDLE"
    )


# --------------------------------------------------------------------------- consultation request


@route("crm:consultation")
@command("consultation")
def start_consultation_request(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    session.reset()
    return HandlerResult(
        reply=Reply(text_key="bot.crm.ask_phone", expects="phone"),
        next_state="crm:awaiting_phone",
    )


@state("crm:awaiting_phone")
def capture_phone(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if event.kind == "command":
        session.reset()
        return _main_menu(ctx)

    text = (event.text or "").strip()
    if not _looks_like_phone(text):
        return HandlerResult(
            reply=Reply(text_key="bot.crm.invalid_phone", expects="phone"),
            next_state="crm:awaiting_phone",
        )

    bot, contact = _bot_and_contact(ctx, event)
    services.create_lead(bot=bot, contact=contact, source=LeadSource.CONSULTATION_REQUEST, phone=text)

    session.reset()
    return HandlerResult(
        reply=Reply(text_key="bot.crm.phone_received", choices=_menu_choices(ctx)), next_state="IDLE"
    )


# --------------------------------------------------------------------------- feedback


@route("crm:feedback")
@command("feedback")
def start_feedback(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    session.reset()
    return HandlerResult(
        reply=Reply(
            text_key="bot.crm.ask_rating",
            choices=[
                # Namespaced `feedback:`, not `crm:` — this sub-route is not in any
                # manifest's `menu` tuple, so the router's feature check falls back to
                # the string before the first `:` as the owning feature slug (see
                # `apps.bot_runtime.router.owning_feature`). "crm" is the app name, not
                # a real feature; "feedback" is, and matching it is what lets a signed
                # tap actually reach this handler instead of silently falling back to
                # the main menu.
                Choice(label_key=f"literal:{'⭐' * i}", value=f"feedback:rate.{i}")
                for i in range(1, 6)
            ],
        ),
        next_state="IDLE",
    )


@route("feedback:rate")
def rate(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    if not value.isdigit() or not 1 <= int(value) <= 5:
        return _main_menu(ctx)

    bot, contact = _bot_and_contact(ctx, event)
    services.record_feedback(bot=bot, contact=contact, rating=int(value))

    return HandlerResult(
        reply=Reply(text_key="bot.crm.feedback_received", choices=_menu_choices(ctx)), next_state="IDLE"
    )
