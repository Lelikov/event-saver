"""Tests for MeetingLinkProjection."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from event_saver.domain.models.event import ParsedEvent, RawEventData
from event_saver.infrastructure.persistence.projections.meeting_projection import MeetingLinkProjection


def _make_event(event_type: str, payload: dict[str, Any] | None = None) -> ParsedEvent:
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


class TestMeetingLinkProjection:
    @pytest.mark.anyio
    async def test_url_created_upserts_link(self) -> None:
        organizer = uuid.uuid4()
        projection = MeetingLinkProjection()
        event = _make_event(
            "meeting.url_created",
            payload={"original": {"meeting_url": "https://meet.example.com/room", "recipient_role": "organizer"}},
        )

        result = await projection.handle(
            event=event,
            booking_ref_id=42,
            organizer_user_id=organizer,
            client_user_id=None,
            queue_name="events.meeting.lifecycle",
        )

        assert result is not None
        sql, params = result
        assert "insert into booking_meeting_links" in sql
        assert "on conflict (booking_ref_id, user_id) do update" in sql
        assert params["meeting_url"] == "https://meet.example.com/room"
        assert params["user_id"] == str(organizer)

    @pytest.mark.anyio
    async def test_url_deleted_removes_link(self) -> None:
        client = uuid.uuid4()
        projection = MeetingLinkProjection()
        event = _make_event("meeting.url_deleted", payload={"original": {"recipient_role": "client"}})

        result = await projection.handle(
            event=event,
            booking_ref_id=42,
            organizer_user_id=None,
            client_user_id=client,
            queue_name="events.meeting.lifecycle",
        )

        assert result is not None
        sql, params = result
        assert "delete from booking_meeting_links" in sql
        assert params["user_id"] == str(client)

    @pytest.mark.anyio
    async def test_no_participant_user_id_returns_none(self) -> None:
        projection = MeetingLinkProjection()
        event = _make_event("meeting.url_created", payload={"original": {"meeting_url": "https://x"}})

        result = await projection.handle(
            event=event,
            booking_ref_id=42,
            organizer_user_id=None,
            client_user_id=None,
            queue_name="events.meeting.lifecycle",
        )

        assert result is None

    def test_can_handle_only_meeting_url_events(self) -> None:
        projection = MeetingLinkProjection()

        assert projection.can_handle(_make_event("meeting.url_created")) is True
        assert projection.can_handle(_make_event("meeting.url_deleted")) is True
        assert projection.can_handle(_make_event("booking.created")) is False
