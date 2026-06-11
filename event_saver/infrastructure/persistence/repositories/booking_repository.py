"""Repository for booking persistence - pure CRUD operations."""

import uuid
from datetime import datetime

from event_schemas.queues import BOOKING_LIFECYCLE_SAVER_QUEUE

from event_saver.domain.models.booking import BookingData
from event_saver.interfaces.sql import ISqlExecutor


class BookingRepository:
    """Repository for bookings table."""

    def __init__(self, sql: ISqlExecutor) -> None:
        self._sql = sql

    async def upsert(
        self,
        *,
        booking_data: BookingData,
        occurred_at: datetime,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
    ) -> int:
        """Insert or update booking. Returns booking ID."""
        row = await self._sql.fetch_one(
            """
            insert into bookings (
                booking_uid,
                first_seen_at,
                last_seen_at,
                start_time,
                end_time,
                current_status,
                organizer_user_id,
                client_user_id
            ) values (
                :booking_uid,
                :first_seen_at,
                :last_seen_at,
                :start_time,
                :end_time,
                :current_status,
                :organizer_user_id,
                :client_user_id
            )
            on conflict (booking_uid) do update
            set
                last_seen_at = greatest(bookings.last_seen_at, excluded.last_seen_at),
                start_time = coalesce(excluded.start_time, bookings.start_time),
                end_time = coalesce(excluded.end_time, bookings.end_time),
                current_status = coalesce(excluded.current_status, bookings.current_status),
                organizer_user_id = coalesce(excluded.organizer_user_id, bookings.organizer_user_id),
                client_user_id = coalesce(excluded.client_user_id, bookings.client_user_id),
                updated_at = now()
            returning id
            """,
            {
                "booking_uid": booking_data.booking_id,
                "first_seen_at": occurred_at,
                "last_seen_at": occurred_at,
                "start_time": booking_data.start_time,
                "end_time": booking_data.end_time,
                "current_status": booking_data.status,
                "organizer_user_id": str(organizer_user_id) if organizer_user_id is not None else None,
                "client_user_id": str(client_user_id) if client_user_id is not None else None,
            },
        )

        if row is None:
            msg = f"Failed to upsert booking: {booking_data.booking_id}"
            raise RuntimeError(msg)

        return int(row["id"])

    async def find_by_booking_uid(self, booking_uid: str) -> int | None:
        """Find booking ID by booking_uid."""
        row = await self._sql.fetch_one(
            """
            select id
            from bookings
            where booking_uid = :booking_uid
            limit 1
            """,
            {"booking_uid": booking_uid},
        )
        return int(row["id"]) if row is not None else None

    async def get_or_none(
        self,
        *,
        booking_id: str,
        queue_name: str,
    ) -> int | None:
        """Get booking ID if exists, respecting queue routing.

        Lifecycle events always force an upsert (they carry status/time changes),
        so for the saver's booking-lifecycle queue this returns None.
        """
        if queue_name == BOOKING_LIFECYCLE_SAVER_QUEUE.name:
            return None
        return await self.find_by_booking_uid(booking_id)

    async def update_client(
        self,
        *,
        booking_ref_id: int,
        client_user_id: uuid.UUID,
    ) -> None:
        """Explicitly set client_user_id on a booking (for client reassignment)."""
        await self._sql.execute(
            """
            update bookings
            set client_user_id = :client_user_id, updated_at = now()
            where id = :booking_ref_id
            """,
            {"booking_ref_id": booking_ref_id, "client_user_id": str(client_user_id)},
        )

    async def save_organizer_history(
        self,
        *,
        booking_id: int,
        organizer_user_id: uuid.UUID,
        source_event_id: str,
        occurred_at: datetime,
    ) -> None:
        """Save organizer assignment to history."""
        await self._sql.fetch_one(
            """
            insert into booking_organizer_history (
                booking_ref_id,
                organizer_user_id,
                source_event_id,
                effective_from
            )
            select
                :booking_ref_id,
                :organizer_user_id,
                :source_event_id,
                :effective_from
            where (
                (
                    select boh.organizer_user_id
                    from booking_organizer_history boh
                    where boh.booking_ref_id = :booking_ref_id
                    order by boh.effective_from desc, boh.id desc
                    limit 1
                ) is distinct from :organizer_user_id
            )
            returning id
            """,
            {
                "booking_ref_id": booking_id,
                "organizer_user_id": str(organizer_user_id),
                "source_event_id": source_event_id,
                "effective_from": occurred_at,
            },
        )
