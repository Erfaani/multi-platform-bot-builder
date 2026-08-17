"""The dispatcher (BOT_RUNTIME.md §1).

Takes a persisted raw update and drives it through: resolve context → parse → load
session → route → handle → render → send.

A handler exception must never take the bot down or leave the user stuck mid-flow, so a
failure logs with the trace id, resets the session to a safe state, and replies with a
localized apology rather than silence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.utils import timezone

from apps.bot_runtime import handlers as handler_registry
from apps.bot_runtime.callbacks import InvalidCallback, encode
from apps.bot_runtime.context import BotContext, resolve_context
from apps.bot_runtime.gateway import deliver
from apps.bot_runtime.models import BusinessContact, InboundUpdate
from apps.bot_runtime.router import resolve
from apps.bot_runtime.sessions import Session, load_session, save_session
from apps.core.events import publish
from apps.core.request_context import get_request_id
from apps.platforms.base import InboundEvent, RenderContext, Reply, RenderedMessage
from apps.platforms.preview.messages import translate
from apps.platforms.registry import capabilities_for, get_adapter
from apps.platforms.rendering import render_with_capabilities

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DispatchResult:
    handled: bool
    route: str = ""
    reply_text: str = ""
    error: str = ""


def resolve_locale(event: InboundEvent, session: Session, ctx: BotContext) -> str:
    """Locale for this conversation.

    Order: the user's stored choice → the platform's hint → the bot's default. A user
    who explicitly picked a language must not have it overridden by their client locale.
    """
    from django.conf import settings

    active = settings.ACTIVE_LOCALES

    if session.locale in active:
        return session.locale
    if event.locale_hint:
        hint = event.locale_hint.split("-")[0]
        if hint in active:
            return hint
    return ctx.default_locale if ctx.default_locale in active else settings.LANGUAGE_CODE


def upsert_contact(event: InboundEvent, ctx: BotContext, locale: str) -> BusinessContact:
    """Record the end user. Tenant-scoped, with no login — never a platform account."""
    contact, _ = BusinessContact.objects.update_or_create(
        bot_id=ctx.bot_id,
        platform=ctx.platform,
        platform_user_id=event.user_ref,
        defaults={
            "tenant_id": ctx.tenant_id,
            "display_name": event.user_display_name[:128],
            "username": event.username[:64],
            "locale": locale,
            "last_seen_at": timezone.now(),
        },
    )
    return contact


def _render(reply: Reply, ctx: BotContext, locale: str) -> tuple[RenderedMessage, list[list[str]]]:
    """Render a reply for the target platform and mint signed callback payloads."""
    render_ctx = RenderContext(
        locale=locale, business_name=ctx.bot_name, translate=translate
    )
    message = render_with_capabilities(reply, render_ctx, capabilities_for(ctx.platform))

    # Callback payloads are built per rendered row so they line up with the buttons.
    callback_values: list[list[str]] = []
    if reply.choices and message.buttons:
        flat: list[str] = []
        for choice in reply.choices:
            # `choice.value` is either a bare route ("business:contact") or a route with
            # a packed sub-value ("faq:list.42", spec's list-then-detail convention).
            # `encode()` always appends a `.` before the value — even an empty one — so
            # passing the whole string as `route` with value="" leaves an unsplit
            # sub-value glued to a stray trailing dot once decoded. Splitting here first
            # is what makes `decode()` hand the handler back a clean `(route, value)`.
            route, _, value = choice.value.partition(".")
            try:
                flat.append(encode(ctx.instance_public_id, route, value))
            except InvalidCallback:
                # Too long to fit Telegram's 64-byte cap — fall back to a plain
                # keyboard rather than shipping a button that will be rejected.
                logger.warning("Callback payload too long for route %s", choice.value)
                return message, []

        index = 0
        for row in message.buttons:
            callback_values.append(flat[index : index + len(row)])
            index += len(row)

    return message, callback_values


def dispatch_update(update: InboundUpdate) -> DispatchResult:
    """Process one inbound update end to end."""
    instance = update.instance
    ctx = resolve_context(instance)
    adapter = get_adapter(ctx.platform)

    event = adapter.parse(update.raw, ctx.instance_public_id)
    if not event.chat_ref or not event.user_ref:
        _mark(update, InboundUpdate.Status.IGNORED)
        return DispatchResult(handled=False, error="no chat or user reference")

    session = load_session(
        bot_id=ctx.bot_id,
        platform=ctx.platform,
        chat_ref=event.chat_ref,
        user_ref=event.user_ref,
    )
    locale = resolve_locale(event, session, ctx)
    contact = upsert_contact(event, ctx, locale)
    _record_analytics(event, ctx, contact)

    resolution = resolve(event, session, ctx, locale)

    try:
        result = resolution.handler(event, session, ctx, value=resolution.value, locale=locale)
    except Exception as exc:
        logger.exception(
            "Handler %s failed for instance %s", resolution.route, ctx.instance_public_id
        )
        _bump_error_count(ctx)
        # Reset so the user is not trapped in a broken flow, and say something.
        session.reset()
        save_session(session)
        message, _ = _render(Reply(text_key="bot.error.generic"), ctx, locale)
        deliver(instance=instance, chat_ref=event.chat_ref, message=message)
        _mark(update, InboundUpdate.Status.FAILED, error=f"{type(exc).__name__}: {exc}")
        return DispatchResult(handled=False, route=resolution.route, error=str(exc))

    if resolution.session_expired:
        result.follow_ups.insert(0, result.reply)
        result.reply = Reply(text_key="bot.session.expired")

    session.state = result.next_state or session.state
    if result.next_state is None and resolution.route == "core:menu":
        session.reset()
    session.locale = locale
    save_session(session)

    message, callback_values = _render(result.reply, ctx, locale)
    deliver(
        instance=instance,
        chat_ref=event.chat_ref,
        message=message,
        callback_values=callback_values,
    )

    for follow_up in result.follow_ups:
        extra, extra_callbacks = _render(follow_up, ctx, locale)
        deliver(
            instance=instance,
            chat_ref=event.chat_ref,
            message=extra,
            callback_values=extra_callbacks,
        )

    for event_type, payload in result.events:
        publish(event_type, {**payload, "bot_id": ctx.bot_public_id, "tenant_id": str(ctx.tenant_id)})

    _mark(update, InboundUpdate.Status.PROCESSED)
    instance.__class__.objects.filter(pk=instance.pk).update(last_update_at=timezone.now())

    return DispatchResult(handled=True, route=resolution.route, reply_text=message.text)


def _mark(update: InboundUpdate, status: str, error: str = "") -> None:
    update.status = status
    update.processed_at = timezone.now()
    update.error = error[:2000]
    update.save(update_fields=["status", "processed_at", "error"])


def _record_analytics(event: InboundEvent, ctx: BotContext, contact) -> None:
    from apps.analytics.models import EventType
    from apps.analytics.services import record_event

    kind = EventType.COMMAND_USED if event.kind == "command" else EventType.MESSAGE_RECEIVED
    record_event(
        tenant_id=ctx.tenant_id,
        bot_id=ctx.bot_id,
        event_type=kind,
        label=(event.text or "")[:64] if event.kind == "command" else "",
        contact_id=getattr(contact, "pk", None),
    )


def _bump_error_count(ctx: BotContext) -> None:
    from django.db.models import F

    from apps.bots.models import Bot

    Bot.objects.filter(pk=ctx.bot_id).update(error_count=F("error_count") + 1)


def simulate_start(instance) -> RenderedMessage:
    """Run a synthetic `/start` through the real pipeline.

    Used by the provisioning smoke test: a bot that provisions cleanly but cannot
    actually answer should be caught by us, not by the customer. Nothing is sent —
    this stops at rendering.
    """
    ctx = resolve_context(instance)
    event = InboundEvent(
        platform=ctx.platform,
        instance_public_id=ctx.instance_public_id,
        chat_ref="smoke-test",
        user_ref="smoke-test",
        kind="command",
        text="/start",
    )
    session = Session(
        bot_id=ctx.bot_id, platform=ctx.platform, chat_ref="smoke-test", user_ref="smoke-test"
    )
    locale = ctx.default_locale

    resolution = resolve(event, session, ctx, locale)
    result = resolution.handler(event, session, ctx, value=resolution.value, locale=locale)
    message, _ = _render(result.reply, ctx, locale)
    return message
