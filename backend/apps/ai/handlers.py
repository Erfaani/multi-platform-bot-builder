"""The AI assistant conversation flow.

Stateless by design: every reachable path is a free-text question in, one answer out, no
`session.state` — because the router's free-text fallback (`apps.bot_runtime.router`,
branch 5) already re-invokes `ai:ask` for the *next* message too, once `ai_assistant` is
bought there is never a reason to hold conversational state just to keep asking.

`@command("ask")` gives a customer an explicit `/ask <question>` alongside the implicit
"just type your question" path the free-text fallback provides — matching the
`@route(...) @command(...)` pairing every other free-text flow in this codebase uses.
"""

from __future__ import annotations

from apps.bot_runtime.handlers import HandlerResult, command, route
from apps.platforms.base import Reply

from apps.ai import services


def _bot_and_contact(ctx, event):
    from apps.bot_runtime.models import BusinessContact
    from apps.bots.models import Bot

    bot = Bot.objects.select_related("tenant").get(pk=ctx.bot_id)
    contact = BusinessContact.objects.get(
        bot_id=ctx.bot_id, platform=ctx.platform, platform_user_id=event.user_ref
    )
    return bot, contact


def _question_text(event) -> str:
    text = (event.text or "").strip()
    if event.kind == "command" and text:
        # Strip the leading "/ask" (and any "@botname" the group-chat form carries).
        parts = text.split(maxsplit=1)
        text = parts[1].strip() if len(parts) > 1 else ""
    return text


@route("ai:ask")
@command("ask")
def ask(event, session, ctx, value: str = "", locale: str = "en") -> HandlerResult:
    question = _question_text(event)
    if not question:
        return HandlerResult(reply=Reply(text_key="bot.ai.prompt", expects="text"))

    bot, contact = _bot_and_contact(ctx, event)
    answer = services.answer_question(bot=bot, contact=contact, question=question, locale=locale)

    if answer.budget_exceeded:
        return HandlerResult(reply=Reply(text_key="bot.ai.unavailable"))
    if answer.provider_error:
        return HandlerResult(reply=Reply(text_key="bot.ai.error"))
    if not answer.grounded or not answer.text:
        return HandlerResult(reply=Reply(text_key="bot.ai.dont_know"))

    return HandlerResult(reply=Reply(text_key="bot.ai.answer", params={"answer": answer.text}))
