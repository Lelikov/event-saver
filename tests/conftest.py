"""Shared test fixtures for event-saver."""

import os

os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import uuid
from datetime import UTC, datetime

import pytest

from event_saver.domain.models.booking import BookingData
from event_saver.domain.models.event import ParsedEvent, RawEventData


@pytest.fixture
def sample_raw_event() -> RawEventData:
    return RawEventData(
        event_id="evt-001",
        event_type="booking.created",
        source="booking",
        occurred_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        booking_id="book-123",
        payload={
            "normalized": {
                "participants": [
                    {"role": "organizer", "user_id": str(uuid.uuid4())},
                    {"role": "client", "user_id": str(uuid.uuid4())},
                ],
            },
            "original": {
                "start_time": "2026-01-20T10:00:00Z",
                "end_time": "2026-01-20T11:00:00Z",
            },
        },
    )


@pytest.fixture
def sample_parsed_event(sample_raw_event: RawEventData) -> ParsedEvent:
    return ParsedEvent(raw=sample_raw_event, payload_hash="abc123hash")


@pytest.fixture
def sample_booking_data() -> BookingData:
    return BookingData(
        booking_id="book-123",
        start_time=datetime(2026, 1, 20, 10, 0, tzinfo=UTC),
        end_time=datetime(2026, 1, 20, 11, 0, tzinfo=UTC),
        status="created",
    )
