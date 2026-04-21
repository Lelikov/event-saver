"""Projection for meeting links."""

import uuid
from typing import Any

from event_schemas.types import EventType

from event_saver.domain.models.event import ParsedEvent
from event_saver.infrastructure.persistence.projections.base import BaseProjection


class MeetingLinkProjection(BaseProjection):
    """Projects meeting URL creation events to booking_meeting_links table."""

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type == EventType.MEETING_URL_CREATED

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        meeting_url = event.payload.get("meeting_url")
        user_id = organizer_user_id or client_user_id

        if user_id is None:
            return None

        return (
            """
            insert into booking_meeting_links (
                booking_ref_id,
                user_id,
                meeting_url,
                source_event_id,
                occurred_at,
                updated_at
            ) values (
                :booking_ref_id,
                :user_id,
                :meeting_url,
                :source_event_id,
                :occurred_at,
                now()
            )
            on conflict (booking_ref_id, user_id) do update
            set
                user_id = excluded.user_id,
                meeting_url = excluded.meeting_url,
                source_event_id = excluded.source_event_id,
                occurred_at = excluded.occurred_at,
                updated_at = now()
            """,
            {
                "booking_ref_id": booking_ref_id,
                "user_id": str(user_id),
                "meeting_url": meeting_url,
                "source_event_id": event.event_id,
                "occurred_at": event.occurred_at,
            },
        )
