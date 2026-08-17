"""Outbound Gateway (BOT_RUNTIME.md §7).

**The only code permitted to call a platform HTTP API.** Feature handlers return data;
they never send. That single rule is what makes rate limiting, retries, auditing and the
preview adapter all possible at once.

Telegram's documented limits are ~30 messages/second per bot and ~1/second per chat. We
apply them *before* being throttled rather than reacting to 429s, because a throttled bot
delays every customer on the platform sharing that worker.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.bots import credentials as credential_service
from apps.bots.models import BotPlatformInstance
from apps.bot_runtime.models import BusinessContact, OutboundMessage
from apps.core.metrics import OUTBOUND_SEND_TOTAL
from apps.platforms.base import ButtonLayout, RenderedMessage
from apps.platforms.clients import get_client, has_client
from apps.platforms.transport import PlatformApiError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after: float = 0.0


def _bucket_take(key: str, rate_per_second: int, window: int = 1) -> RateLimitDecision:
    """Fixed-window counter in the cache.

    Deliberately simple: an approximate limiter that is always *below* the platform's
    ceiling is worth more than an exact one that occasionally exceeds it.
    """
    if rate_per_second <= 0:
        return RateLimitDecision(True)

    slot = int(time.time() // window)
    slot_key = f"rate:{key}:{slot}"

    try:
        added = cache.add(slot_key, 1, window + 1)
        count = 1 if added else cache.incr(slot_key)
    except ValueError:
        # The key expired between `add` and `incr`; treat as a fresh window.
        cache.set(slot_key, 1, window + 1)
        count = 1

    if count > rate_per_second:
        return RateLimitDecision(False, retry_after=window)
    return RateLimitDecision(True)


def check_rate_limits(instance_id: int, chat_ref: str) -> RateLimitDecision:
    per_bot = _bucket_take(
        f"bot:{instance_id}", settings.OUTBOUND_RATE_PER_BOT_PER_SECOND
    )
    if not per_bot.allowed:
        return per_bot
    return _bucket_take(
        f"chat:{instance_id}:{chat_ref}", settings.OUTBOUND_RATE_PER_CHAT_PER_SECOND
    )


def _reply_markup(message: RenderedMessage, callback_values: list[list[str]] | None) -> dict | None:
    """Turn rendered buttons into the platform's keyboard structure."""
    if not message.buttons:
        return None

    if message.layout == ButtonLayout.INLINE and callback_values:
        return {
            "inline_keyboard": [
                [
                    {"text": label, "callback_data": data}
                    for label, data in zip(row, values, strict=False)
                ]
                for row, values in zip(message.buttons, callback_values, strict=False)
            ]
        }

    if message.layout in (ButtonLayout.REPLY, ButtonLayout.INLINE):
        return {
            "keyboard": [[{"text": label} for label in row] for row in message.buttons],
            "resize_keyboard": True,
            "one_time_keyboard": False,
        }

    return None


def queue_message(
    *,
    instance: BotPlatformInstance,
    chat_ref: str,
    message: RenderedMessage,
    callback_values: list[list[str]] | None = None,
    is_bulk: bool = False,
) -> OutboundMessage:
    """Record the intent to send, then hand off to the sender.

    The row is created *before* dispatch, so a crash between deciding to reply and
    actually replying is visible and recoverable rather than silent.
    """
    payload = {
        "text": message.text,
        "reply_markup": _reply_markup(message, callback_values),
    }
    return OutboundMessage.objects.create(
        instance=instance,
        chat_ref=chat_ref,
        payload=payload,
        status=OutboundMessage.Status.QUEUED,
        is_bulk=is_bulk,
    )


def send_now(outbound: OutboundMessage) -> OutboundMessage:
    """Attempt one delivery. Safe to call repeatedly — it is the retry path too."""
    if outbound.status == OutboundMessage.Status.SENT:
        return outbound

    instance = outbound.instance

    decision = check_rate_limits(instance.pk, outbound.chat_ref)
    if not decision.allowed:
        OUTBOUND_SEND_TOTAL.labels(outcome="rate_limited").inc()
        return _defer(outbound, seconds=decision.retry_after, reason="rate limited locally")

    if not has_client(instance.platform):
        # A channel with no client yet. Park rather than fail: the message is a valid
        # intent that simply has nowhere to go.
        return _defer(outbound, seconds=3600, reason="platform transport not implemented")

    outbound.attempt += 1
    try:
        token = credential_service.read_token(instance=instance, purpose="send_message")
        result = get_client(instance.platform, token).send_message(
            chat_id=outbound.chat_ref,
            text=outbound.payload.get("text", ""),
            reply_markup=outbound.payload.get("reply_markup"),
        )
    except PlatformApiError as exc:
        return _handle_send_error(outbound, exc)
    except Exception as exc:
        logger.exception("Unexpected error sending message %s", outbound.pk)
        return _retry_or_fail(outbound, f"{type(exc).__name__}: {exc}")

    outbound.status = OutboundMessage.Status.SENT
    outbound.platform_message_id = str(result.get("message_id", ""))
    outbound.sent_at = timezone.now()
    outbound.error = ""
    outbound.save(
        update_fields=["status", "attempt", "platform_message_id", "sent_at", "error", "updated_at"]
    )

    OUTBOUND_SEND_TOTAL.labels(outcome="sent").inc()
    BotPlatformInstance.objects.filter(pk=instance.pk).update(last_send_at=timezone.now())
    return outbound


def _handle_send_error(outbound: OutboundMessage, exc: PlatformApiError) -> OutboundMessage:
    if exc.is_rate_limited:
        # Honour the platform's own figure exactly — guessing risks another 429.
        OUTBOUND_SEND_TOTAL.labels(outcome="rate_limited").inc()
        return _defer(outbound, seconds=exc.retry_after or 30, reason="platform rate limit")

    if exc.is_permanent:
        # Blocked by the user, or the chat is gone. Retrying forever helps nobody and
        # burns quota, so stop and record why.
        _mark_contact_unreachable(outbound)
        outbound.status = OutboundMessage.Status.DROPPED
        outbound.error = str(exc)[:1000]
        outbound.save(update_fields=["status", "attempt", "error", "updated_at"])
        OUTBOUND_SEND_TOTAL.labels(outcome="dropped").inc()
        return outbound

    return _retry_or_fail(outbound, str(exc))


def _mark_contact_unreachable(outbound: OutboundMessage) -> None:
    BusinessContact.objects.filter(
        bot=outbound.instance.bot,
        platform=outbound.instance.platform,
        platform_user_id=outbound.chat_ref,
    ).update(is_blocked=True)


def _defer(outbound: OutboundMessage, *, seconds: float, reason: str) -> OutboundMessage:
    outbound.status = OutboundMessage.Status.QUEUED
    outbound.next_attempt_at = timezone.now() + timedelta(seconds=max(1.0, seconds))
    outbound.error = reason[:1000]
    outbound.save(
        update_fields=["status", "attempt", "next_attempt_at", "error", "updated_at"]
    )
    return outbound


def _retry_or_fail(outbound: OutboundMessage, error: str) -> OutboundMessage:
    if outbound.attempt >= MAX_ATTEMPTS:
        outbound.status = OutboundMessage.Status.FAILED
        outbound.error = error[:1000]
        outbound.save(update_fields=["status", "attempt", "error", "updated_at"])
        OUTBOUND_SEND_TOTAL.labels(outcome="failed").inc()
        return outbound

    # Exponential backoff with jitter, so a platform blip does not produce a
    # synchronised retry stampede from every bot at once.
    OUTBOUND_SEND_TOTAL.labels(outcome="retrying").inc()
    backoff = (2**outbound.attempt) + random.uniform(0, 1)
    return _defer(outbound, seconds=backoff, reason=error)


def deliver(
    *,
    instance: BotPlatformInstance,
    chat_ref: str,
    message: RenderedMessage,
    callback_values: list[list[str]] | None = None,
    is_bulk: bool = False,
) -> OutboundMessage:
    """Queue and attempt a send in one call — the normal path for a reply."""
    outbound = queue_message(
        instance=instance,
        chat_ref=chat_ref,
        message=message,
        callback_values=callback_values,
        is_bulk=is_bulk,
    )
    return send_now(outbound)
