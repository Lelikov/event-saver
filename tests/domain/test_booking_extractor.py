"""Tests for BookingDataExtractor domain service."""

from datetime import UTC, datetime

from event_saver.domain.services.booking_extractor import BookingDataExtractor


class TestExtract:
    def setup_method(self) -> None:
        self.extractor = BookingDataExtractor()

    def test_booking_created_extracts_status(self) -> None:
        result = self.extractor.extract(
            booking_id="book-1",
            event_type="booking.created",
            payload={
                "original": {
                    "start_time": "2026-01-20T10:00:00Z",
                    "end_time": "2026-01-20T11:00:00Z",
                },
            },
        )

        assert result.booking_id == "book-1"
        assert result.status == "created"
        assert result.start_time == datetime(2026, 1, 20, 10, 0, tzinfo=UTC)
        assert result.end_time == datetime(2026, 1, 20, 11, 0, tzinfo=UTC)

    def test_booking_cancelled_status(self) -> None:
        result = self.extractor.extract(
            booking_id="book-1",
            event_type="booking.cancelled",
            payload={"original": {}},
        )

        assert result.status == "cancelled"

    def test_unknown_event_type_no_status(self) -> None:
        result = self.extractor.extract(
            booking_id="book-1",
            event_type="booking.rescheduled",
            payload={"original": {}},
        )

        assert result.status is None

    def test_missing_original_returns_none_times(self) -> None:
        result = self.extractor.extract(
            booking_id="book-1",
            event_type="booking.created",
            payload={},
        )

        assert result.start_time is None
        assert result.end_time is None
        assert result.status == "created"


class TestEnvelopeUnwrap:
    def test_extracts_times_from_enveloped_payload(self) -> None:
        extractor = BookingDataExtractor()
        payload = {
            "original": {"start_time": "2026-03-01T10:00:00+00:00", "end_time": "2026-03-01T11:00:00+00:00"},
            "normalized": {"participants": []},
        }

        data = extractor.extract(booking_id="b-1", event_type="booking.created", payload=payload)

        assert data.start_time is not None
        assert data.end_time is not None

    def test_tolerates_bare_payload(self) -> None:
        extractor = BookingDataExtractor()
        payload = {"start_time": "2026-03-01T10:00:00+00:00", "end_time": "2026-03-01T11:00:00+00:00"}

        data = extractor.extract(booking_id="b-1", event_type="booking.created", payload=payload)

        assert data.start_time is not None
