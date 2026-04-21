"""Tests for ProjectionExecutor application service."""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from event_saver.application.services.projection_executor import ProjectionExecutor
from event_saver.domain.models.event import ParsedEvent, RawEventData


def _make_event(event_type: str = "booking.created") -> ParsedEvent:
    return ParsedEvent(
        raw=RawEventData(
            event_id="evt-001",
            event_type=event_type,
            source="booking",
            occurred_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            booking_id="book-123",
            payload={},
        ),
        payload_hash="hash123",
    )


class FakeProjection:
    def __init__(self, *, handles: bool, result: tuple[str, dict[str, Any]] | None = None) -> None:
        self._handles = handles
        self._result = result
        self.handle_called = False

    def can_handle(self, _event: ParsedEvent) -> bool:
        return self._handles

    async def handle(self, **_kwargs: Any) -> tuple[str, dict[str, Any]] | None:
        self.handle_called = True
        return self._result


class FailingProjection:
    def can_handle(self, _event: ParsedEvent) -> bool:
        return True

    async def handle(self, **_kwargs: Any) -> tuple[str, dict[str, Any]] | None:
        raise ValueError("projection broke")


class TestExecuteProjections:
    @pytest.mark.asyncio
    async def test_executes_matching_handler(self) -> None:
        sql = AsyncMock()
        handler = FakeProjection(handles=True, result=("INSERT INTO t VALUES (:v)", {"v": 1}))
        executor = ProjectionExecutor(sql=sql, handlers=[handler])

        await executor.execute_projections(
            event=_make_event(),
            queue_name="events.booking.lifecycle",
            booking_ref_id=1,
            organizer_user_id=uuid.uuid4(),
            client_user_id=uuid.uuid4(),
        )

        assert handler.handle_called
        sql.execute.assert_called_once_with("INSERT INTO t VALUES (:v)", {"v": 1})

    @pytest.mark.asyncio
    async def test_skips_non_matching_handler(self) -> None:
        sql = AsyncMock()
        handler = FakeProjection(handles=False)
        executor = ProjectionExecutor(sql=sql, handlers=[handler])

        await executor.execute_projections(
            event=_make_event(),
            queue_name="events.booking.lifecycle",
            booking_ref_id=1,
            organizer_user_id=None,
            client_user_id=None,
        )

        assert not handler.handle_called
        sql.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_returning_none_skips_sql(self) -> None:
        sql = AsyncMock()
        handler = FakeProjection(handles=True, result=None)
        executor = ProjectionExecutor(sql=sql, handlers=[handler])

        await executor.execute_projections(
            event=_make_event(),
            queue_name="events.booking.lifecycle",
            booking_ref_id=1,
            organizer_user_id=None,
            client_user_id=None,
        )

        assert handler.handle_called
        sql.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_projection_failure_propagates(self) -> None:
        sql = AsyncMock()
        handler = FailingProjection()
        executor = ProjectionExecutor(sql=sql, handlers=[handler])

        with pytest.raises(ValueError, match="projection broke"):
            await executor.execute_projections(
                event=_make_event(),
                queue_name="events.booking.lifecycle",
                booking_ref_id=1,
                organizer_user_id=None,
                client_user_id=None,
            )
