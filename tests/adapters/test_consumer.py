"""Tests for RabbitEventConsumerRunner message handling, retry and DLQ classification."""

import inspect
import json
from typing import Any

import pytest
from faststream.exceptions import NackMessage, RejectMessage
from sqlalchemy.exc import OperationalError

from event_saver.adapters.consumer import RabbitEventConsumerRunner, _is_transient


class FakeMessage:
    def __init__(self, headers: dict[str, str], body: bytes) -> None:
        self.headers = headers
        self.body = body


class FakeEventStore:
    """Event store that raises queued exceptions before succeeding."""

    def __init__(self, failures: list[BaseException] | None = None) -> None:
        self.failures = list(failures or [])
        self.calls: list[dict[str, Any]] = []

    async def save_event(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)


def _cloud_event_message(payload: dict[str, Any] | None = None) -> FakeMessage:
    headers = {
        "ce-specversion": "1.0",
        "ce-id": "evt-001",
        "ce-type": "booking.created",
        "ce-source": "booking",
        "ce-time": "2026-01-15T10:00:00+00:00",
        "ce-bookingid": "book-123",
        "ce-idempotencykey": "idem-1",
        "ce-traceid": "trace-1",
        "content-type": "application/json",
    }
    return FakeMessage(headers=headers, body=json.dumps(payload or {"original": {}}).encode())


def _runner(event_store: FakeEventStore, attempts: int = 3) -> RabbitEventConsumerRunner:
    return RabbitEventConsumerRunner(
        broker=object(),  # type: ignore[arg-type]
        exchange=object(),  # type: ignore[arg-type]
        event_store=event_store,
        transient_retry_attempts=attempts,
        retry_backoff_seconds=0.0,
    )


def _transient_error() -> OperationalError:
    return OperationalError("select 1", None, ConnectionRefusedError("db down"))


class TestConsumeSuccess:
    @pytest.mark.anyio
    async def test_saves_event_with_extracted_attributes(self) -> None:
        store = FakeEventStore()
        runner = _runner(store)

        await runner._consume_message(message=_cloud_event_message(), queue_name="events.jitsi")  # noqa: SLF001

        assert len(store.calls) == 1
        call = store.calls[0]
        assert call["queue_name"] == "events.jitsi"
        assert call["event_id"] == "evt-001"
        assert call["booking_id"] == "book-123"
        assert call["idempotency_key"] == "idem-1"
        assert call["trace_id"] == "trace-1"


class TestTransientRetry:
    @pytest.mark.anyio
    async def test_retries_transient_error_then_succeeds(self) -> None:
        store = FakeEventStore(failures=[_transient_error(), _transient_error()])
        runner = _runner(store, attempts=3)

        await runner._consume_message(message=_cloud_event_message(), queue_name="events.jitsi")  # noqa: SLF001

        assert len(store.calls) == 3

    @pytest.mark.anyio
    async def test_exhausted_retries_nack_with_requeue(self) -> None:
        """Transient outage must requeue, never dead-letter (24h-TTL DLQ = data loss)."""
        store = FakeEventStore(failures=[_transient_error()] * 3)
        runner = _runner(store, attempts=3)

        with pytest.raises(NackMessage) as exc_info:
            await runner._consume_message(message=_cloud_event_message(), queue_name="events.jitsi")  # noqa: SLF001

        assert len(store.calls) == 3
        assert exc_info.value.extra_options == {"requeue": True}


class TestPoisonMessages:
    @pytest.mark.anyio
    async def test_non_transient_error_rejects_to_dlq_without_retry(self) -> None:
        store = FakeEventStore(failures=[ValueError("bad payload shape")] * 3)
        runner = _runner(store, attempts=3)

        with pytest.raises(RejectMessage):
            await runner._consume_message(message=_cloud_event_message(), queue_name="events.jitsi")  # noqa: SLF001

        assert len(store.calls) == 1  # no retry for poison

    @pytest.mark.anyio
    async def test_unparseable_cloudevent_rejects_to_dlq(self) -> None:
        store = FakeEventStore()
        runner = _runner(store)
        message = FakeMessage(headers={}, body=b"not a cloudevent")

        with pytest.raises(RejectMessage):
            await runner._consume_message(message=message, queue_name="events.jitsi")  # noqa: SLF001

        assert store.calls == []


class TestTransientClassification:
    def test_db_connectivity_errors_are_transient(self) -> None:
        assert _is_transient(_transient_error()) is True
        assert _is_transient(ConnectionResetError("reset")) is True
        assert _is_transient(TimeoutError("pool timeout")) is True

    def test_validation_errors_are_poison(self) -> None:
        assert _is_transient(ValueError("bad")) is False
        assert _is_transient(KeyError("missing")) is False


class TestHandlerFactory:
    def test_queue_name_is_not_a_handler_parameter(self) -> None:
        """Queue name must be closure-captured, not a signature default a body field could override."""
        runner = _runner(FakeEventStore())

        handler = runner._make_handler("events.jitsi")  # noqa: SLF001

        assert "_queue_name" not in inspect.signature(handler).parameters
        assert "queue_name" not in inspect.signature(handler).parameters

    @pytest.mark.anyio
    async def test_handler_uses_captured_queue_name(self) -> None:
        store = FakeEventStore()
        runner = _runner(store)
        handler = runner._make_handler("events.mail")  # noqa: SLF001

        await handler(message=_cloud_event_message())

        assert store.calls[0]["queue_name"] == "events.mail"
