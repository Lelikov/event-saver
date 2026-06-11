"""Tests for notification projections (email, telegram, status history)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from event_saver.domain.models.event import ParsedEvent, RawEventData
from event_saver.infrastructure.persistence.projections.notification_projection import (
    EmailNotificationProjection,
    EmailStatusHistoryProjection,
    TelegramNotificationProjection,
)


def _make_event(event_type: str, payload: dict[str, Any]) -> ParsedEvent:
    return ParsedEvent(
        raw=RawEventData(
            event_id="evt-001",
            event_type=event_type,
            source="notification",
            occurred_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            booking_id="book-123",
            payload=payload,
        ),
        payload_hash="hash123",
    )


def _handle_kwargs(
    organizer_user_id: uuid.UUID | None = None,
    client_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return {
        "booking_ref_id": 42,
        "organizer_user_id": organizer_user_id,
        "client_user_id": client_user_id,
        "queue_name": "events.notification.delivery",
    }


class TestEmailNotificationProjection:
    @pytest.mark.anyio
    async def test_email_sent_resolves_organizer_user_id(self) -> None:
        organizer = uuid.uuid4()
        projection = EmailNotificationProjection()
        event = _make_event(
            "notification.email.message_sent",
            {
                "original": {
                    "job_id": "job-1",
                    "users": [{"role": "organizer", "email": "org@example.com"}],
                    "trigger_event": "booking.created",
                    "email": "org@example.com",
                },
            },
        )

        result = await projection.handle(event=event, **_handle_kwargs(organizer_user_id=organizer))

        assert result is not None
        sql, params = result
        assert "booking_email_notifications" in sql
        assert params["job_id"] == "job-1"
        assert params["user_id"] == str(organizer)
        assert params["recipient_email"] == "org@example.com"

    @pytest.mark.anyio
    async def test_unknown_role_yields_null_user_id(self) -> None:
        projection = EmailNotificationProjection()
        event = _make_event(
            "notification.email.message_sent",
            {"original": {"job_id": "job-1", "users": [{"role": "previous_organizer"}]}},
        )

        result = await projection.handle(event=event, **_handle_kwargs(client_user_id=uuid.uuid4()))

        assert result is not None
        _, params = result
        assert params["user_id"] is None

    @pytest.mark.anyio
    async def test_missing_job_id_returns_none(self) -> None:
        projection = EmailNotificationProjection()
        event = _make_event("notification.email.message_sent", {"original": {}})

        result = await projection.handle(event=event, **_handle_kwargs())

        assert result is None

    @pytest.mark.anyio
    async def test_unisender_status_updates_last_status(self) -> None:
        projection = EmailNotificationProjection()
        event = _make_event(
            "unisender.events.v1.transactional.status.create",
            {
                "original": {
                    "event_data": {
                        "job_id": "job-1",
                        "status": "delivered",
                        "event_time": "2026-01-15 10:05:00",
                        "email": "org@example.com",
                    },
                },
            },
        )

        result = await projection.handle(event=event, **_handle_kwargs())

        assert result is not None
        _, params = result
        assert params["last_status"] == "delivered"
        assert params["job_id"] == "job-1"


class TestTelegramNotificationProjection:
    @pytest.mark.anyio
    async def test_resolves_client_user_id(self) -> None:
        client = uuid.uuid4()
        projection = TelegramNotificationProjection()
        event = _make_event(
            "notification.telegram.message_sent",
            {
                "original": {
                    "users": [{"role": "client"}],
                    "trigger_event": "booking.created",
                    "email": "client@example.com",
                },
            },
        )

        result = await projection.handle(event=event, **_handle_kwargs(client_user_id=client))

        assert result is not None
        sql, params = result
        assert "booking_telegram_notifications" in sql
        assert params["user_id"] == str(client)

    @pytest.mark.anyio
    async def test_unknown_role_returns_none(self) -> None:
        """Telegram rows must not be attributed to the client when the role is unknown."""
        projection = TelegramNotificationProjection()
        event = _make_event(
            "notification.telegram.message_sent",
            {"original": {"users": [{"role": "previous_organizer"}]}},
        )

        result = await projection.handle(event=event, **_handle_kwargs(client_user_id=uuid.uuid4()))

        assert result is None


class TestEmailStatusHistoryProjection:
    @pytest.mark.anyio
    async def test_handles_unisender_status_event(self) -> None:
        projection = EmailStatusHistoryProjection()
        event = _make_event(
            "unisender.events.v1.transactional.status.create",
            {
                "original": {
                    "event_data": {
                        "job_id": "job-1",
                        "status": "clicked",
                        "url": "https://example.com",
                        "event_time": "2026-01-15 10:05:00",
                    },
                },
            },
        )

        assert projection.can_handle(event) is True
        result = await projection.handle(event=event, **_handle_kwargs())

        assert result is not None
