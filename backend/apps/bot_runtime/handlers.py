"""Feature handler contract and registry (BOT_RUNTIME.md §6).

A handler is a pure-ish function: `(event, session, ctx) -> HandlerResult`. It returns
data; it never sends anything, never emits a literal string, and never queries across
tenants. That is what makes handlers unit-testable with no network and no database, and
what lets the preview adapter render the same objects the runtime does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from apps.platforms.base import Reply

#: A handler signature: (InboundEvent, Session, BotContext) -> HandlerResult
Handler = Callable[..., "HandlerResult"]


@dataclass(slots=True)
class HandlerResult:
    reply: Reply
    next_state: str | None = None
    #: Domain events to publish once the reply is queued.
    events: list[tuple[str, dict]] = field(default_factory=list)
    #: Extra replies sent after the main one (confirmations, attachments).
    follow_ups: list[Reply] = field(default_factory=list)


_ROUTES: dict[str, Handler] = {}
_STATE_HANDLERS: dict[str, Handler] = {}
_COMMANDS: dict[str, Handler] = {}


def route(name: str) -> Callable[[Handler], Handler]:
    """Register a handler for a `feature:action` route."""

    def decorator(handler: Handler) -> Handler:
        _ROUTES[name] = handler
        return handler

    return decorator


def state(name: str) -> Callable[[Handler], Handler]:
    """Register a handler for a conversation state (multi-step flows)."""

    def decorator(handler: Handler) -> Handler:
        _STATE_HANDLERS[name] = handler
        return handler

    return decorator


def command(name: str) -> Callable[[Handler], Handler]:
    """Register a `/command` handler."""

    def decorator(handler: Handler) -> Handler:
        _COMMANDS[name.lstrip("/")] = handler
        return handler

    return decorator


def get_route(name: str) -> Handler | None:
    return _ROUTES.get(name)


def get_state_handler(name: str) -> Handler | None:
    return _STATE_HANDLERS.get(name)


def get_command(name: str) -> Handler | None:
    return _COMMANDS.get(name.lstrip("/").lower())


def known_routes() -> set[str]:
    return set(_ROUTES)


def owning_feature(route_name: str) -> str:
    """`appointment:book` → `appointment`. Used to check the bot bought the feature."""
    return route_name.split(":", 1)[0]


def load_feature_handlers() -> None:
    """Import every app's handler module so the decorators run.

    Called once at app-ready. Handlers live with their feature, so a new feature
    registers itself simply by existing.
    """
    import importlib

    from django.apps import apps as django_apps

    for app_config in django_apps.get_app_configs():
        try:
            importlib.import_module(f"{app_config.name}.handlers")
        except ModuleNotFoundError:
            continue
