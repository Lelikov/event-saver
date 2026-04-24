"""Projection for meeting links."""

import uuid
from typing import Any

from event_schemas.types import EventType

from event_saver.domain.models.event import ParsedEvent
from event_saver.infrastructure.persistence.projections.base import BaseProjection


class MeetingLinkProjection(BaseProjection):
    """Projects meeting URL creation/deletion events to booking_meeting_links table."""

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type in {EventType.MEETING_URL_CREATED, EventType.MEETING_URL_DELETED}

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        user_id = organizer_user_id or client_user_id
        if user_id is None:
            return None

        if event.event_type == EventType.MEETING_URL_DELETED:
            return self._handle_deleted(booking_ref_id=booking_ref_id, user_id=user_id)

        return self._handle_created(booking_ref_id=booking_ref_id, user_id=user_id, event=event)

    @staticmethod
    def _handle_created(
        *,
        booking_ref_id: int,
        user_id: uuid.UUID,
        event: ParsedEvent,
    ) -> tuple[str, dict[str, Any]] | None:
        original = event.payload.get("original", event.payload)
        meeting_url = original.get("meeting_url")

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

    @staticmethod
    def _handle_deleted(
        *,
        booking_ref_id: int,
        user_id: uuid.UUID,
    ) -> tuple[str, dict[str, Any]] | None:
        return (
            """
            delete from booking_meeting_links
            where booking_ref_id = :booking_ref_id
              and user_id = :user_id
            """,
            {
                "booking_ref_id": booking_ref_id,
                "user_id": str(user_id),
            },
        )
