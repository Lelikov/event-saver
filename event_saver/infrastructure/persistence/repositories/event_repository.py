"""Repository for event persistence - pure CRUD operations."""


import ujson

from event_saver.domain.models.event import ParsedEvent
from event_saver.interfaces.sql import ISqlExecutor


class EventRepository:
    """Repository for raw events table.

    Handles only data persistence - no business logic.
    """

    def __init__(self, sql: ISqlExecutor) -> None:
        self._sql = sql

    async def save(self, event: ParsedEvent) -> bool:
        """Save event to events table with deduplication.

        Returns:
            True if event was inserted, False if duplicate was skipped

        """
        payload_json = ujson.dumps(event.payload)

        row = await self._sql.fetch_one(
            """
            insert into events (
                event_id,
                booking_id,
                event_type,
                source,
                hash,
                occurred_at,
                payload
            ) values (
                :event_id,
                :booking_id,
                :event_type,
                :source,
                :hash,
                :occurred_at,
                cast(:payload as jsonb)
            )
            on conflict (booking_id, event_type, source, hash) do nothing
            returning event_id
            """,
            {
                "event_id": event.event_id,
                "booking_id": event.booking_id,
                "event_type": event.event_type,
                "source": event.source,
                "hash": event.payload_hash,
                "occurred_at": event.occurred_at,
                "payload": payload_json,
            },
        )

        return row is not None
