"""Projection for booking lifecycle events."""

import json
import uuid
from typing import Any

from event_schemas.types import EventType

from event_saver.domain.models.event import ParsedEvent
from event_saver.infrastructure.persistence.projections.base import BaseProjection

_LIFECYCLE_TYPES = {
    EventType.BOOKING_CREATED,
    EventType.BOOKING_RESCHEDULED,
    EventType.BOOKING_REASSIGNED,
    EventType.BOOKING_CANCELLED,
}

_ACTION_MAP: dict[str, str] = {
    EventType.BOOKING_CREATED: "created",
    EventType.BOOKING_RESCHEDULED: "rescheduled",
    EventType.BOOKING_REASSIGNED: "reassigned",
    EventType.BOOKING_CANCELLED: "cancelled",
}


class LifecycleProjection(BaseProjection):
    """Projects booking lifecycle events to booking_lifecycle_events table."""

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type in _LIFECYCLE_TYPES

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        action = _ACTION_MAP.get(event.event_type)
        if action is None:
            return None

        details = self._extract_details(event)

        return (
            """
            insert into booking_lifecycle_events (
                booking_ref_id,
                raw_event_id,
                action,
                actor_user_id,
                details,
                occurred_at
            ) values (
                :booking_ref_id,
                :raw_event_id,
                :action,
                :actor_user_id,
                :details,
                :occurred_at
            )
            on conflict (raw_event_id) do nothing
            """,
            {
                "booking_ref_id": booking_ref_id,
                "raw_event_id": event.event_id,
                "action": action,
                "actor_user_id": str(organizer_user_id) if organizer_user_id else None,
                "details": json.dumps(details) if details else None,
                "occurred_at": event.occurred_at,
            },
        )

    @staticmethod
    def _extract_details(event: ParsedEvent) -> dict[str, Any] | None:
        original = event.payload.get("original", {})

        if event.event_type == EventType.BOOKING_CREATED:
            return _pick(original, "start_time", "end_time")

        if event.event_type == EventType.BOOKING_RESCHEDULED:
            details = _pick(original, "start_time", "end_time")
            previous = original.get("previous_booking", {})
            prev_start = previous.get("start_time")
            if prev_start is not None:
                details["previous_start_time"] = prev_start
            return details

        if event.event_type == EventType.BOOKING_REASSIGNED:
            normalized = event.payload.get("normalized", {})
            participants = normalized.get("participants", [])
            for p in participants:
                if p.get("role") == "previous_organizer":
                    return {"previous_organizer": p.get("user_id")}
            return None

        if event.event_type == EventType.BOOKING_CANCELLED:
            return _pick(original, "cancellation_reason")

        return None


def _pick(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Pick specified keys from a dictionary, omitting missing keys."""
    return {k: source[k] for k in keys if k in source}
