"""Tests for VideoEventProjection."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from event_saver.adapters.event_classification import BookingTimelineClassifier
from event_saver.domain.models.event import ParsedEvent, RawEventData
from event_saver.infrastructure.persistence.projections.video_projection import VideoEventProjection


def _make_event(event_type: str, payload: dict[str, Any] | None = None) -> ParsedEvent:
    return ParsedEvent(
        raw=RawEventData(
            event_id="evt-001",
            event_type=event_type,
            source="jitsi",
            occurred_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            booking_id="book-123",
            payload=payload or {},
        ),
        payload_hash="hash123",
    )


def _projection() -> VideoEventProjection:
    return VideoEventProjection(classifier=BookingTimelineClassifier())


_HANDLE_DEFAULTS: dict[str, Any] = {
    "booking_ref_id": 42,
    "organizer_user_id": None,
    "client_user_id": None,
    "queue_name": "events.jitsi",
}


class TestVideoEventProjection:
    def test_can_handle_only_jitsi_events(self) -> None:
        projection = _projection()

        assert projection.can_handle(_make_event("jitsi.conference.joined")) is True
        assert projection.can_handle(_make_event("booking.created")) is False

    @pytest.mark.anyio
    async def test_conference_joined_resolves_role_and_strips_payload(self) -> None:
        organizer = uuid.uuid4()
        event = _make_event(
            "jitsi.conference.joined",
            payload={
                "original": {
                    "context": {"user": {"role": "organizer"}},
                    "time": "2026-01-15T10:00:05Z",
                    "noise": "dropped",
                },
            },
        )

        result = await _projection().handle(
            event=event,
            booking_ref_id=42,
            organizer_user_id=organizer,
            client_user_id=None,
            queue_name="events.jitsi",
        )

        assert result is not None
        sql, params = result
        assert "insert into booking_video_events" in sql
        assert params["video_event_type"] == "conference.joined"
        assert params["participant_role"] == "organizer"
        assert params["user_id"] == str(organizer)
        assert json.loads(params["payload"]) == {}  # conference events store no payload

    @pytest.mark.anyio
    async def test_mute_event_keeps_only_muted_flag(self) -> None:
        event = _make_event(
            "jitsi.audio.mute_status_changed",
            payload={"original": {"muted": True, "context": {"user": {"role": "client"}}}},
        )

        result = await _projection().handle(event=event, **_HANDLE_DEFAULTS)

        assert result is not None
        _, params = result
        assert json.loads(params["payload"]) == {"muted": True}

    @pytest.mark.anyio
    async def test_unknown_role_yields_null_user_id(self) -> None:
        event = _make_event(
            "jitsi.conference.left",
            payload={"original": {"context": {"user": {}}}},
        )

        result = await _projection().handle(event=event, **_HANDLE_DEFAULTS)

        assert result is not None
        _, params = result
        assert params["user_id"] is None
        assert params["participant_role"] is None
