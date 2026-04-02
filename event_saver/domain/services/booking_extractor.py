"""Domain service for extracting booking data from event payloads."""

from datetime import UTC, datetime
from typing import Any

from event_saver.domain.models.booking import BookingData
from event_saver.event_types import EventType


class BookingDataExtractor:
    """Extract booking information from event payloads.

    Only specific event types contain booking lifecycle data.
    """

    def extract(
        self,
        *,
        booking_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> BookingData:
        """Extract booking data from event.

        Returns BookingData with only fields that can be extracted from this event type.
        """
        return BookingData(
            booking_id=booking_id,
            start_time=self._extract_datetime(event_type, payload, "start_time"),
            end_time=self._extract_datetime(event_type, payload, "end_time"),
            status=self._extract_status(event_type),
        )

    @staticmethod
    def _extract_datetime(
        event_type: str,
        payload: dict[str, Any],
        field_name: str,
    ) -> datetime | None:
        """Extract start_time or end_time from booking.created event."""
        if event_type != EventType.BOOKING_CREATED:
            return None

        value = payload.get(field_name)
        if isinstance(value, datetime):
            return value

        if not isinstance(value, str) or not value:
            return None

        candidate = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None

    @staticmethod
    def _extract_status(event_type: str) -> str | None:
        """Map event type to booking status."""
        if event_type == EventType.BOOKING_CREATED:
            return "created"
        if event_type == EventType.BOOKING_CANCELLED:
            return "cancelled"
        return None
