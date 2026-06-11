"""Tests for LifecycleProjection."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from event_saver.domain.models.event import ParsedEvent, RawEventData
from event_saver.infrastructure.persistence.projections.lifecycle_projection import LifecycleProjection


def _make_event(
    event_type: str = "booking.created",
    payload: dict[str, Any] | None = None,
) -> ParsedEvent:
    return ParsedEvent(
        raw=RawEventData(
            event_id="evt-001",
            event_type=event_type,
            source="booking",
            occurred_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            booking_id="book-123",
            payload=payload or {},
        ),
        payload_hash="hash123",
    )


_HANDLE_DEFAULTS: dict[str, Any] = {
    "booking_ref_id": 42,
    "organizer_user_id": None,
    "client_user_id": None,
    "queue_name": "events.booking.lifecycle.saver",
}


class TestCanHandle:
    def test_returns_true_for_booking_created(self) -> None:
        projection = LifecycleProjection()
        assert projection.can_handle(_make_event("booking.created")) is True

    def test_returns_true_for_booking_rescheduled(self) -> None:
        projection = LifecycleProjection()
        assert projection.can_handle(_make_event("booking.rescheduled")) is True

    def test_returns_true_for_booking_reassigned(self) -> None:
        projection = LifecycleProjection()
        assert projection.can_handle(_make_event("booking.reassigned")) is True

    def test_returns_true_for_booking_cancelled(self) -> None:
        projection = LifecycleProjection()
        assert projection.can_handle(_make_event("booking.cancelled")) is True

    def test_returns_true_for_booking_rejected(self) -> None:
        projection = LifecycleProjection()
        assert projection.can_handle(_make_event("booking.rejected")) is True

    def test_returns_false_for_booking_reminder_sent(self) -> None:
        projection = LifecycleProjection()
        assert projection.can_handle(_make_event("booking.reminder_sent")) is False

    def test_returns_false_for_getstream_message_new(self) -> None:
        projection = LifecycleProjection()
        assert projection.can_handle(_make_event("getstream.message.new")) is False


class TestHandleCreated:
    @pytest.mark.anyio
    async def test_extracts_start_and_end_time(self) -> None:
        event = _make_event(
            "booking.created",
            payload={
                "original": {
                    "start_time": "2026-01-20T10:00:00Z",
                    "end_time": "2026-01-20T11:00:00Z",
                },
            },
        )
        projection = LifecycleProjection()
        result = await projection.handle(event=event, **_HANDLE_DEFAULTS)

        assert result is not None
        _sql, params = result
        assert params["action"] == "created"
        details = json.loads(params["details"])
        assert details == {"start_time": "2026-01-20T10:00:00Z", "end_time": "2026-01-20T11:00:00Z"}

    @pytest.mark.anyio
    async def test_passes_through_user_ids(self) -> None:
        org_id = uuid.uuid4()
        client_id = uuid.uuid4()
        event = _make_event(
            "booking.created",
            payload={"original": {"start_time": "2026-01-20T10:00:00Z"}},
        )
        projection = LifecycleProjection()
        result = await projection.handle(
            event=event,
            booking_ref_id=42,
            organizer_user_id=org_id,
            client_user_id=client_id,
            queue_name="events.booking.lifecycle.saver",
        )

        assert result is not None
        _, params = result
        assert params["organizer_user_id"] == str(org_id)
        assert params["client_user_id"] == str(client_id)


class TestHandleRescheduled:
    @pytest.mark.anyio
    async def test_extracts_times_and_previous_start(self) -> None:
        event = _make_event(
            "booking.rescheduled",
            payload={
                "original": {
                    "start_time": "2026-02-01T09:00:00Z",
                    "end_time": "2026-02-01T10:00:00Z",
                    "previous_start_time": "2026-01-20T09:00:00Z",
                    "previous_booking_uid": "old-uid-123",
                },
            },
        )
        projection = LifecycleProjection()
        result = await projection.handle(event=event, **_HANDLE_DEFAULTS)

        assert result is not None
        _, params = result
        assert params["action"] == "rescheduled"
        details = json.loads(params["details"])
        assert details == {
            "start_time": "2026-02-01T09:00:00Z",
            "end_time": "2026-02-01T10:00:00Z",
            "previous_start_time": "2026-01-20T09:00:00Z",
            "previous_booking_uid": "old-uid-123",
        }


class TestHandleReassigned:
    @pytest.mark.anyio
    async def test_finds_previous_organizer_user_id(self) -> None:
        prev_org_id = str(uuid.uuid4())
        event = _make_event(
            "booking.reassigned",
            payload={
                "original": {},
                "normalized": {
                    "participants": [
                        {"role": "organizer", "user_id": str(uuid.uuid4())},
                        {"role": "previous_organizer", "user_id": prev_org_id},
                        {"role": "client", "user_id": str(uuid.uuid4())},
                    ],
                },
            },
        )
        projection = LifecycleProjection()
        result = await projection.handle(event=event, **_HANDLE_DEFAULTS)

        assert result is not None
        _, params = result
        assert params["action"] == "reassigned"
        details = json.loads(params["details"])
        assert details == {"previous_organizer": prev_org_id}


class TestHandleRejected:
    @pytest.mark.anyio
    async def test_extracts_rejection_details(self) -> None:
        event = _make_event(
            "booking.rejected",
            payload={
                "original": {
                    "client_email": "client@example.com",
                    "rejection_type": "no_slots",
                    "rejection_reasons": ["volunteer_unavailable"],
                    "available_from": "2026-02-01T00:00:00Z",
                    "has_active_booking": True,
                    "active_booking_start": "2026-01-25T10:00:00Z",
                },
            },
        )
        projection = LifecycleProjection()
        result = await projection.handle(event=event, **_HANDLE_DEFAULTS)

        assert result is not None
        _, params = result
        assert params["action"] == "rejected"
        details = json.loads(params["details"])
        assert details == {
            "rejection_type": "no_slots",
            "rejection_reasons": ["volunteer_unavailable"],
            "available_from": "2026-02-01T00:00:00Z",
            "has_active_booking": True,
            "active_booking_start": "2026-01-25T10:00:00Z",
        }


class TestHandleCancelled:
    @pytest.mark.anyio
    async def test_extracts_cancellation_reason(self) -> None:
        event = _make_event(
            "booking.cancelled",
            payload={
                "original": {
                    "cancellation_reason": "Client requested cancellation",
                },
            },
        )
        projection = LifecycleProjection()
        result = await projection.handle(event=event, **_HANDLE_DEFAULTS)

        assert result is not None
        _, params = result
        assert params["action"] == "cancelled"
        details = json.loads(params["details"])
        assert details == {"cancellation_reason": "Client requested cancellation"}

    @pytest.mark.anyio
    async def test_null_reason_yields_none_details(self) -> None:
        event = _make_event(
            "booking.cancelled",
            payload={
                "original": {
                    "cancellation_reason": None,
                },
            },
        )
        projection = LifecycleProjection()
        result = await projection.handle(event=event, **_HANDLE_DEFAULTS)

        assert result is not None
        _, params = result
        assert params["action"] == "cancelled"
        assert params["details"] is None
