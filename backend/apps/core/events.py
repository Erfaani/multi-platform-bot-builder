"""Domain events and the transactional outbox writer.

``publish()`` only ever writes a row. It must be called inside the same transaction
as the state change it describes — that is what makes the event and the change
atomic, and what lets a failed consumer be replayed (ARCHITECTURE.md §9).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from django.db import transaction

from apps.core.models import OutboxMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base class for domain events. Subclasses add their own payload fields."""

    event_type: str = "domain.event"

    def payload(self) -> dict[str, Any]:
        data = asdict(self) if is_dataclass(self) else dict(self.__dict__)
        data.pop("event_type", None)
        return data


def publish(event: DomainEvent | str, payload: dict[str, Any] | None = None) -> OutboxMessage:
    """Append an event to the outbox.

    Raises if called outside a transaction in a context that expects atomicity —
    an event committed without its state change is worse than no event at all.
    """
    if isinstance(event, str):
        event_type, body = event, (payload or {})
    else:
        event_type, body = event.event_type, event.payload()

    message = OutboxMessage.objects.create(event_type=event_type, payload=body)
    transaction.on_commit(lambda: _schedule_relay(message.pk))
    return message


def _schedule_relay(message_pk: int) -> None:
    """Nudge the relay to publish this event promptly.

    Failures here are **swallowed on purpose**. The event is already committed to the
    outbox, so this call is an accelerator, not the delivery guarantee — and it runs in
    an ``on_commit`` hook, where an exception would surface as a 500 on a request whose
    work already succeeded. A broker outage must not fail checkout after the order has
    been written.

    `core.tasks.sweep_pending_outbox` is the safety net: it re-queues anything that was
    never picked up. That is precisely the case this guard hands to it.
    """
    from apps.core.tasks import relay_outbox_message

    try:
        relay_outbox_message.delay(message_pk)
    except Exception:
        logger.warning(
            "Could not enqueue outbox message %s; the periodic sweep will retry it.",
            message_pk,
            exc_info=True,
        )
