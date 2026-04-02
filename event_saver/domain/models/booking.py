"""Domain model for booking data."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class BookingData:
    """Booking information extracted from event.

    Value object containing booking lifecycle data.
    Only fields that can be extracted from specific events are present.
    """

    booking_id: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: str | None = None
