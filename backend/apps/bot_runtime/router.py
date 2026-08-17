"""Routing (BOT_RUNTIME.md §5).

The router contains **no feature knowledge**. Routes come from feature manifests, and
handlers register themselves; this module only decides *which* of them to call:

    session in a flow   → the owning feature's state handler
    a /command          → the command registry
    a callback          → the signed route it carries
    a menu label        → that menu's route
    otherwise           → AI fallback if bought, else the main menu
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from apps.bot_runtime import handlers as handler_registry
from apps.bot_runtime.callbacks import InvalidCallback, decode
from apps.bot_runtime.context import BotContext
from apps.bot_runtime.sessions import Session
from apps.features.registry import all_manifests, manifests_for
from apps.platforms.base import InboundEvent
from apps.platforms.preview.messages import translate

logger = logging.getLogger(__name__)

MAIN_MENU_ROUTE = "core:menu"


@dataclass(frozen=True, slots=True)
class Resolution:
    handler: handler_registry.Handler
    route: str
    value: str = ""
    #: Set when a stale session was discarded, so the reply can explain the reset.
    session_expired: bool = False


def menu_routes_for(ctx: BotContext, locale: str) -> dict[str, str]:
    """Visible menu label → route, for the features this bot actually has."""
    routes: dict[str, str] = {}
    for manifest in manifests_for(ctx.enabled_features):
        for entry in manifest.menu:
            label = translate(entry.label_key, locale=locale)
            routes[label.strip().casefold()] = entry.route
    return routes


@lru_cache(maxsize=1)
def _route_owners() -> dict[str, str]:
    """Route → the feature slug that owns it, taken from the manifests.

    Derived from declarations rather than from the route string: a route namespace is a
    UI grouping (`business:contact`) and does not have to equal a feature slug
    (`contact`). Inferring one from the other silently denied valid routes.
    """
    owners: dict[str, str] = {}
    for slug, manifest in all_manifests().items():
        for entry in manifest.menu:
            owners[entry.route] = slug
    return owners


def _feature_allows(ctx: BotContext, route: str) -> bool:
    """A route is only callable if the bot bought the feature that owns it.

    Enforced here rather than in each handler: a signed callback minted before a
    feature was removed must stop working the moment it is removed.
    """
    if route.startswith("core:"):
        return True

    owner = _route_owners().get(route)
    if owner is None:
        # A sub-action of a declared route, e.g. `faq:list` reached via a callback.
        owner = handler_registry.owning_feature(route)
    return ctx.has_feature(owner)


def resolve(event: InboundEvent, session: Session, ctx: BotContext, locale: str) -> Resolution:
    fallback = Resolution(
        handler=handler_registry.get_route(MAIN_MENU_ROUTE),
        route=MAIN_MENU_ROUTE,
        session_expired=session.was_stale,
    )

    # 1. Mid-flow: the owning feature decides what the next input means.
    if not session.is_idle:
        state_handler = handler_registry.get_state_handler(session.state)
        if state_handler is not None:
            return Resolution(handler=state_handler, route=session.state)
        # The state's feature was removed, or the code changed under a live session.
        logger.info("No handler for session state %s; resetting", session.state)
        session.reset()
        return fallback

    # 2. Commands.
    if event.kind == "command" and event.text:
        name = event.text.lstrip("/").split()[0].split("@")[0].lower()
        command_handler = handler_registry.get_command(name)
        if command_handler is not None:
            return Resolution(handler=command_handler, route=f"command:{name}")

    # 3. Callbacks — signed, so a crafted payload cannot reach an unbought feature.
    if event.kind == "callback" and event.payload.get("data"):
        try:
            route, value = decode(ctx.instance_public_id, event.payload["data"])
        except InvalidCallback:
            logger.warning("Rejected an unverified callback on instance %s", ctx.instance_public_id)
            return fallback

        handler = handler_registry.get_route(route)
        if handler is not None and _feature_allows(ctx, route):
            return Resolution(handler=handler, route=route, value=value)
        return fallback

    # 4. A tapped reply-keyboard label arrives as ordinary text.
    if event.text:
        route = menu_routes_for(ctx, locale).get(event.text.strip().casefold())
        if route:
            handler = handler_registry.get_route(route)
            if handler is not None and _feature_allows(ctx, route):
                return Resolution(handler=handler, route=route)

    # 5. Free text: hand to the assistant if the customer bought it.
    if ctx.has_feature("ai_assistant"):
        ai_handler = handler_registry.get_route("ai:ask")
        if ai_handler is not None:
            return Resolution(handler=ai_handler, route="ai:ask")

    return fallback
