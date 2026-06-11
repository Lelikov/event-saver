"""Tests for EventRepository."""

import json
from datetime import UTC, datetime

import pytest

from event_saver.domain.models.event import ParsedEvent, RawEventData
from event_saver.infrastructure.persistence.repositories.event_repository import EventRepository
from tests.fakes import FakeSqlExecutor


def _event(idempotency_key: str | None = "idem-key-1") -> ParsedEvent:
    return ParsedEvent(
        raw=RawEventData(
            event_id="evt-001",
            event_type="booking.created",
            source="booking",
            occurred_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            booking_id="book-123",
            payload={"original": {"start_time": "2026-01-20T10:00:00Z"}},
            idempotency_key=idempotency_key,
            trace_id="trace-1",
            span_id="span-1",
            dataschema="v1",
        ),
        payload_hash="hash123",
    )


class TestSave:
    @pytest.mark.anyio
    async def test_single_insert_with_bare_on_conflict(self) -> None:
        """One statement, bare ON CONFLICT: no dual-path IntegrityError possible."""
        sql = FakeSqlExecutor(fetch_one_results=[{"event_id": "evt-001"}])
        repo = EventRepository(sql)

        inserted = await repo.save(_event())

        assert inserted is True
        assert len(sql.queries) == 1
        query, _ = sql.queries[0]
        assert "on conflict do nothing" in query
        assert "on conflict (" not in query  # no named conflict target

    @pytest.mark.anyio
    async def test_duplicate_returns_false(self) -> None:
        sql = FakeSqlExecutor(fetch_one_results=[None])
        repo = EventRepository(sql)

        inserted = await repo.save(_event())

        assert inserted is False

    @pytest.mark.anyio
    async def test_passes_all_columns_including_tracing(self) -> None:
        sql = FakeSqlExecutor(fetch_one_results=[{"event_id": "evt-001"}])
        repo = EventRepository(sql)

        await repo.save(_event())

        _, params = sql.queries[0]
        assert params["event_id"] == "evt-001"
        assert params["booking_id"] == "book-123"
        assert params["event_type"] == "booking.created"
        assert params["source"] == "booking"
        assert params["hash"] == "hash123"
        assert params["idempotency_key"] == "idem-key-1"
        assert params["trace_id"] == "trace-1"
        assert params["span_id"] == "span-1"
        assert params["dataschema"] == "v1"
        assert json.loads(params["payload"]) == {"original": {"start_time": "2026-01-20T10:00:00Z"}}

    @pytest.mark.anyio
    async def test_event_without_idempotency_key_uses_same_path(self) -> None:
        sql = FakeSqlExecutor(fetch_one_results=[{"event_id": "evt-001"}])
        repo = EventRepository(sql)

        inserted = await repo.save(_event(idempotency_key=None))

        assert inserted is True
        query, params = sql.queries[0]
        assert "on conflict do nothing" in query
        assert params["idempotency_key"] is None
