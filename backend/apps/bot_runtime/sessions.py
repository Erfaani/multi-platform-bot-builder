"""Conversation sessions (BOT_RUNTIME.md §4).

Redis is the hot copy, the database is the durable one. A worker restart mid-booking
must not lose the appointment the customer was halfway through entering.

A stale session resets to the main menu *with an explanation* rather than silently
misinterpreting the next thing the user types — a half-finished booking that resumes
three days later would otherwise attach today's answer to last week's question.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.bot_runtime.models import BotSession

IDLE = BotSession.IDLE
CACHE_PREFIX = "botsession"


@dataclass
class Session:
    bot_id: int
    platform: str
    chat_ref: str
    user_ref: str
    state: str = IDLE
    context: dict = field(default_factory=dict)
    locale: str = ""
    was_stale: bool = False

    @property
    def is_idle(self) -> bool:
        return self.state == IDLE

    def reset(self) -> None:
        self.state = IDLE
        self.context = {}

    def set(self, key: str, value) -> None:
        self.context[key] = value

    def get(self, key: str, default=None):
        return self.context.get(key, default)


def _key(bot_id: int, platform: str, chat_ref: str, user_ref: str) -> str:
    return f"{CACHE_PREFIX}:{bot_id}:{platform}:{chat_ref}:{user_ref}"


def _ttl() -> int:
    return int(settings.SESSION_IDLE_TIMEOUT_SECONDS)


def load_session(*, bot_id: int, platform: str, chat_ref: str, user_ref: str) -> Session:
    key = _key(bot_id, platform, chat_ref, user_ref)

    cached = cache.get(key)
    if cached is not None:
        return cached

    row = BotSession.objects.filter(
        bot_id=bot_id, platform=platform, chat_ref=chat_ref, user_ref=user_ref
    ).first()

    if row is None:
        return Session(bot_id=bot_id, platform=platform, chat_ref=chat_ref, user_ref=user_ref)

    if row.is_expired:
        # Expired, not absent: tell the caller so it can explain the reset.
        return Session(
            bot_id=bot_id,
            platform=platform,
            chat_ref=chat_ref,
            user_ref=user_ref,
            locale=row.locale,
            was_stale=row.state != IDLE,
        )

    return Session(
        bot_id=bot_id,
        platform=platform,
        chat_ref=chat_ref,
        user_ref=user_ref,
        state=row.state,
        context=row.context or {},
        locale=row.locale,
    )


def save_session(session: Session) -> None:
    """Write through to both copies."""
    expires_at = timezone.now() + timedelta(seconds=_ttl())

    BotSession.objects.update_or_create(
        bot_id=session.bot_id,
        platform=session.platform,
        chat_ref=session.chat_ref,
        user_ref=session.user_ref,
        defaults={
            "state": session.state,
            "context": session.context,
            "locale": session.locale,
            "expires_at": expires_at,
        },
    )

    key = _key(session.bot_id, session.platform, session.chat_ref, session.user_ref)
    session.was_stale = False
    cache.set(key, session, _ttl())


def clear_session(session: Session) -> None:
    session.reset()
    save_session(session)


def purge_expired(limit: int = 5000) -> int:
    """Housekeeping for sessions nobody came back to."""
    stale = BotSession.objects.filter(expires_at__lt=timezone.now()).values_list("pk", flat=True)[
        :limit
    ]
    pks = list(stale)
    BotSession.objects.filter(pk__in=pks).delete()
    return len(pks)
