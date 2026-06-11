"""Tests for ChatEventProjection and ChatReadUpdateProjection."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from event_saver.adapters.event_classification import BookingTimelineClassifier
from event_saver.domain.models.event import ParsedEvent, RawEventData
from event_saver.infrastructure.persistence.projections.chat_projection import (
    ChatEventProjection,
    ChatReadUpdateProjection,
)


def _make_event(
    event_type: str = "getstream.message.new",
    source: str = "getstream",
    payload: dict[str, Any] | None = None,
) -> ParsedEvent:
    return ParsedEvent(
        raw=RawEventData(
            event_id="evt-001",
            event_type=event_type,
            source=source,
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
    "queue_name": "events.chat",
}


class TestChatEventProjection:
    @pytest.mark.anyio
    async def test_projects_getstream_message_with_preview(self) -> None:
        organizer = uuid.uuid4()
        projection = ChatEventProjection(classifier=BookingTimelineClassifier())
        event = _make_event(
            payload={
                "original": {
                    "type": "message.new",
                    "message": {"id": "msg-1", "text": "hello there"},
                },
                "normalized": {"participants": [{"role": "organizer", "user_id": str(organizer)}]},
            },
        )

        result = await projection.handle(
            event=event,
            booking_ref_id=42,
            organizer_user_id=organizer,
            client_user_id=None,
            queue_name="events.chat",
        )

        assert result is not None
        sql, params = result
        assert "insert into booking_chat_events" in sql
        assert params["chat_event_type"] == "message.new"
        assert params["message_id"] == "msg-1"
        assert params["user_id"] == str(organizer)
        assert params["text_preview"] == "hello there"

    @pytest.mark.anyio
    async def test_unmapped_participants_yield_null_user_id(self) -> None:
        projection = ChatEventProjection(classifier=BookingTimelineClassifier())
        event = _make_event(payload={"original": {"type": "message.new"}})

        result = await projection.handle(event=event, **_HANDLE_DEFAULTS)

        assert result is not None
        _, params = result
        assert params["user_id"] is None


class TestChatReadUpdateProjection:
    @pytest.mark.anyio
    async def test_update_marks_null_author_rows_as_read(self) -> None:
        """user_id IS NULL rows (unmapped GetStream authors) must still flip to read."""
        client = uuid.uuid4()
        projection = ChatReadUpdateProjection()
        event = _make_event(
            event_type="getstream.message.read",
            payload={
                "original": {"last_read_message_id": "msg-9"},
                "normalized": {"participants": [{"role": "client", "user_id": str(client)}]},
            },
        )

        result = await projection.handle(
            event=event,
            booking_ref_id=42,
            organizer_user_id=None,
            client_user_id=client,
            queue_name="events.chat",
        )

        assert result is not None
        sql, params = result
        assert "user_id is distinct from :reader_user_id" in sql
        assert "user_id != :reader_user_id" not in sql
        assert params["reader_user_id"] == str(client)
        assert params["last_read_message_id"] == "msg-9"

    @pytest.mark.anyio
    async def test_returns_none_without_reader_user_id(self) -> None:
        projection = ChatReadUpdateProjection()
        event = _make_event(event_type="getstream.message.read", payload={"original": {}})

        result = await projection.handle(event=event, **_HANDLE_DEFAULTS)

        assert result is None
