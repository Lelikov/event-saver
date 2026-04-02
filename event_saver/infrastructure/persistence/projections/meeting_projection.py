"""Projection for meeting links."""

from typing import Any

from event_saver.domain.models.event import ParsedEvent
from event_saver.event_types import EventType
from event_saver.infrastructure.persistence.projections.base import BaseProjection


class MeetingLinkProjection(BaseProjection):
    """Projects meeting URL creation events to booking_meeting_links table.

    Handles: booking.events.v1.meeting.url_created.create
    """

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type == EventType.BOOKING_MEETING_URL_CREATED

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        meeting_url = event.payload.get("meeting_url")
        participant_ref_id = organizer_ref_id or client_ref_id

        if participant_ref_id is None:
            return None

        return (
            """
            insert into booking_meeting_links (
                booking_ref_id,
                participant_ref_id,
                meeting_url,
                source_event_id,
                occurred_at,
                updated_at
            ) values (
                :booking_ref_id,
                :participant_ref_id,
                :meeting_url,
                :source_event_id,
                :occurred_at,
                now()
            )
            on conflict (booking_ref_id, participant_ref_id) do update
            set
                participant_ref_id = excluded.participant_ref_id,
                meeting_url = excluded.meeting_url,
                source_event_id = excluded.source_event_id,
                occurred_at = excluded.occurred_at,
                updated_at = now()
            """,
            {
                "booking_ref_id": booking_ref_id,
                "participant_ref_id": participant_ref_id,
                "meeting_url": meeting_url,
                "source_event_id": event.event_id,
                "occurred_at": event.occurred_at,
            },
        )
