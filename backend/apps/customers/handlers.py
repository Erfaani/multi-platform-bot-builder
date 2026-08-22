"""`/link <code>` — connects a platform account to the website account that generated
the code (spec §47). Deliberately carries no bot-specific meaning of its own: what a
linked identity is then *allowed* to do (the owner-admin menu, `apps.bot_admin`) is
decided elsewhere, by checking `TenantMembership`. This keeps linking a one-time action
that immediately works for every bot the user can already manage from the dashboard,
not something repeated per bot.
"""

from __future__ import annotations

from apps.bot_runtime.handlers import HandlerResult, command
from apps.platforms.base import Reply

from apps.customers.services import consume_link_code


@command("link")
def link_account(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    parts = (event.text or "").split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""

    if not code:
        return HandlerResult(reply=Reply(text_key="bot.link.usage"), next_state="IDLE")

    identity = consume_link_code(
        code=code, platform=ctx.platform, platform_user_id=event.user_ref, username=event.username
    )
    if identity is None:
        return HandlerResult(reply=Reply(text_key="bot.link.invalid_code"), next_state="IDLE")

    return HandlerResult(reply=Reply(text_key="bot.link.success"), next_state="IDLE")
