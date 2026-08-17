"""Bot activity events (spec §31).

A single flat, indexed table. DATABASE.md §10 designs a partitioned `analytics_event`
plus a separate `analytics_daily_rollup` table — real optimizations, but ones that earn
their complexity only once event volume makes a plain indexed table slow. Building the
rollup machinery now, before any bot has produced a single event, would be designing for
a load this platform does not have yet. `services.py` computes summaries with plain
aggregate queries; if that ever shows up in a slow-query log, this is where the rollup
table gets added.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import TenantOwnedModel


class EventType(models.TextChoices):
    MESSAGE_RECEIVED = "message_received", "Message received"
    COMMAND_USED = "command_used", "Command used"
    ROUTE_USED = "route_used", "Menu/route used"


class AnalyticsEvent(TenantOwnedModel):
    bot = models.ForeignKey("bots.Bot", on_delete=models.CASCADE, related_name="analytics_events")
    contact = models.ForeignKey(
        "bot_runtime.BusinessContact",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    #: e.g. the command name or route slug, for a lightweight breakdown without a join.
    label = models.CharField(max_length=64, blank=True)
    properties = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "analytics_event"
        ordering = ("-occurred_at",)
        indexes = [
            models.Index(fields=["bot", "-occurred_at"], name="analytics_bot_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} on {self.bot_id} at {self.occurred_at}"
