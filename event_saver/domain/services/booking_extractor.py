"""Domain service for extracting booking data from event payloads."""

from typing import Any

from event_schemas.envelope import unwrap_payload
from event_schemas.types import EventType

from event_saver.domain.models.booking import BookingData
from event_saver.utils import parse_iso_datetime


_STATUS_BY_EVENT_TYPE: dict[str, str] = {
    EventType.BOOKING_CREATED: "created",
    EventType.BOOKING_CANCELLED: "cancelled",
    # booking.rescheduled: status unchanged, COALESCE preserves existing
    # booking.reassigned: status unchanged
    # booking.reminder_sent: not a status change
}


class BookingDataExtractor:
    """Extract booking information from event payloads.

    Reads start_time/end_time from the original payload (set by event-receiver)
    and derives status from the event type.
    """

    def extract(
        self,
        *,
        booking_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> BookingData:
        """Extract booking data from payload."""
        original = unwrap_payload(payload)
        start_time = original.get("start_time")
        end_time = original.get("end_time")
        status = _STATUS_BY_EVENT_TYPE.get(event_type)

        return BookingData(
            booking_id=booking_id,
            start_time=parse_iso_datetime(start_time),
            end_time=parse_iso_datetime(end_time),
            status=status,
        )
