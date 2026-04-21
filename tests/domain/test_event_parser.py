"""Tests for EventParser domain service."""

import hashlib
import json
from datetime import UTC, datetime

from event_saver.domain.services.event_parser import EventParser


class TestParse:
    def test_parses_valid_event(self) -> None:
        result = EventParser.parse(
            event_id="evt-001",
            event_type="booking.created",
            source="booking",
            time="2026-01-15T10:00:00Z",
            booking_id="book-123",
            data={"key": "value"},
        )

        assert result.event_id == "evt-001"
        assert result.event_type == "booking.created"
        assert result.source == "booking"
        assert result.booking_id == "book-123"
        assert result.payload == {"key": "value"}
        assert result.occurred_at == datetime(2026, 1, 15, 10, 0, tzinfo=UTC)

    def test_none_data_becomes_empty_dict(self) -> None:
        result = EventParser.parse(
            event_id="evt-001",
            event_type="booking.created",
            source="booking",
            time="2026-01-15T10:00:00Z",
            booking_id=None,
            data=None,
        )

        assert result.payload == {}

    def test_none_time_uses_utc_now(self) -> None:
        before = datetime.now(UTC)
        result = EventParser.parse(
            event_id="evt-001",
            event_type="booking.created",
            source="booking",
            time=None,
            booking_id=None,
            data={},
        )
        after = datetime.now(UTC)

        assert before <= result.occurred_at <= after

    def test_datetime_time_preserved(self) -> None:
        dt = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        result = EventParser.parse(
            event_id="evt-001",
            event_type="booking.created",
            source="booking",
            time=dt,
            booking_id=None,
            data={},
        )

        assert result.occurred_at == dt

    def test_naive_datetime_gets_utc(self) -> None:
        dt = datetime(2026, 6, 1, 12, 0)  # noqa: DTZ001
        result = EventParser.parse(
            event_id="evt-001",
            event_type="booking.created",
            source="booking",
            time=dt,
            booking_id=None,
            data={},
        )

        assert result.occurred_at.tzinfo == UTC

    def test_extensions_passed_through(self) -> None:
        result = EventParser.parse(
            event_id="evt-001",
            event_type="booking.created",
            source="booking",
            time="2026-01-15T10:00:00Z",
            booking_id=None,
            data={},
            idempotency_key="idem-1",
            trace_id="trace-1",
            span_id="span-1",
            dataschema="v1",
        )

        assert result.idempotency_key == "idem-1"
        assert result.trace_id == "trace-1"
        assert result.span_id == "span-1"
        assert result.dataschema == "v1"


class TestPayloadHash:
    def test_deterministic_hash(self) -> None:
        result1 = EventParser.parse(
            event_id="e1",
            event_type="t",
            source="s",
            time="2026-01-01T00:00:00Z",
            booking_id=None,
            data={"b": 2, "a": 1},
        )
        result2 = EventParser.parse(
            event_id="e2",
            event_type="t",
            source="s",
            time="2026-01-01T00:00:00Z",
            booking_id=None,
            data={"a": 1, "b": 2},
        )

        assert result1.payload_hash == result2.payload_hash

    def test_hash_matches_sorted_json(self) -> None:
        payload = {"z": 1, "a": 2}
        expected = hashlib.md5(  # noqa: S324
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode(),
        ).hexdigest()

        result = EventParser.parse(
            event_id="e1",
            event_type="t",
            source="s",
            time="2026-01-01T00:00:00Z",
            booking_id=None,
            data=payload,
        )

        assert result.payload_hash == expected
