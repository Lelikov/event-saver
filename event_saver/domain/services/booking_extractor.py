"""Domain service for extracting booking data from event payloads."""

from datetime import UTC, datetime
from typing import Any

from event_saver.domain.models.booking import BookingData


class BookingDataExtractor:
    """Extract booking information from normalized event payloads.

    Expects normalized structure from event-receiver:
    {
        "normalized": {
            "booking": {
                "start_time": "2024-03-01T10:00:00Z",
                "end_time": "2024-03-01T11:00:00Z",
                "status": "created"
            }
        }
    }
    """

    def extract(
        self,
        *,
        booking_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> BookingData:
        """Extract booking data from normalized payload."""
        normalized = payload.get("normalized")
        if not isinstance(normalized, dict):
            return BookingData(booking_id=booking_id)

        booking_data = normalized.get("booking")
        if not isinstance(booking_data, dict):
            return BookingData(booking_id=booking_id)

        start_time = booking_data.get("start_time")
        end_time = booking_data.get("end_time")
        status = booking_data.get("status")

        return BookingData(
            booking_id=booking_id,
            start_time=_parse_datetime(start_time) if start_time else None,
            end_time=_parse_datetime(end_time) if end_time else None,
            status=status if isinstance(status, str) else None,
        )


def _parse_datetime(value: Any) -> datetime | None:
    """Parse datetime from string or return existing datetime object."""
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
