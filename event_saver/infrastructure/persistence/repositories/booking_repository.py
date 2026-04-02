"""Repository for booking persistence - pure CRUD operations."""

from datetime import datetime

from event_saver.domain.models.booking import BookingData
from event_saver.event_types import QueueName
from event_saver.interfaces.sql import ISqlExecutor


class BookingRepository:
    """Repository for bookings table.

    Handles only data persistence - no business logic.
    """

    def __init__(self, sql: ISqlExecutor) -> None:
        self._sql = sql

    async def upsert(
        self,
        *,
        booking_data: BookingData,
        occurred_at: datetime,
        organizer_id: int | None,
        client_id: int | None,
    ) -> int:
        """Insert or update booking.

        Returns booking ID (internal database key).
        Uses coalesce to preserve existing values when new ones are None.
        """
        row = await self._sql.fetch_one(
            """
            insert into bookings (
                booking_uid,
                first_seen_at,
                last_seen_at,
                start_time,
                end_time,
                current_status,
                current_organizer_participant_ref_id,
                current_client_participant_ref_id
            ) values (
                :booking_uid,
                :first_seen_at,
                :last_seen_at,
                :start_time,
                :end_time,
                :current_status,
                :current_organizer_participant_ref_id,
                :current_client_participant_ref_id
            )
            on conflict (booking_uid) do update
            set
                last_seen_at = greatest(bookings.last_seen_at, excluded.last_seen_at),
                start_time = coalesce(excluded.start_time, bookings.start_time),
                end_time = coalesce(excluded.end_time, bookings.end_time),
                current_status = coalesce(excluded.current_status, bookings.current_status),
                current_organizer_participant_ref_id = coalesce(
                    excluded.current_organizer_participant_ref_id,
                    bookings.current_organizer_participant_ref_id
                ),
                current_client_participant_ref_id = coalesce(
                    excluded.current_client_participant_ref_id,
                    bookings.current_client_participant_ref_id
                ),
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
                "current_organizer_participant_ref_id": organizer_id,
                "current_client_participant_ref_id": client_id,
            },
        )

        if row is None:
            msg = f"Failed to upsert booking: {booking_data.booking_id}"
            raise RuntimeError(msg)

        return int(row["id"])

    async def find_by_booking_uid(self, booking_uid: str) -> int | None:
        """Find booking ID by booking_uid.

        Returns internal database ID or None if not found.
        """
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

        For non-lifecycle queues, only returns existing bookings.
        For lifecycle queue, returns None to trigger upsert.
        """
        if queue_name == QueueName.EVENTS_BOOKING_LIFECYCLE:
            return None

        return await self.find_by_booking_uid(booking_id)

    async def save_organizer_history(
        self,
        *,
        booking_id: int,
        organizer_id: int,
        source_event_id: str,
        occurred_at: datetime,
    ) -> None:
        """Save organizer assignment to history.

        Only inserts if organizer is different from current.
        """
        await self._sql.fetch_one(
            """
            insert into booking_organizer_history (
                booking_ref_id,
                organizer_participant_ref_id,
                source_event_id,
                effective_from
            )
            select
                :booking_ref_id,
                :organizer_participant_ref_id,
                :source_event_id,
                :effective_from
            where (
                (
                    select boh.organizer_participant_ref_id
                    from booking_organizer_history boh
                    where boh.booking_ref_id = :booking_ref_id
                    order by boh.effective_from desc, boh.id desc
                    limit 1
                ) is distinct from :organizer_participant_ref_id
            )
            returning id
            """,
            {
                "booking_ref_id": booking_id,
                "organizer_participant_ref_id": organizer_id,
                "source_event_id": source_event_id,
                "effective_from": occurred_at,
            },
        )
