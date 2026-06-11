"""Tests for BookingRepository."""

import uuid
from datetime import UTC, datetime

import pytest
from event_schemas.queues import BOOKING_LIFECYCLE_SAVER_QUEUE

from event_saver.domain.models.booking import BookingData
from event_saver.infrastructure.persistence.repositories.booking_repository import BookingRepository
from tests.fakes import FakeSqlExecutor


_OCCURRED_AT = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


def _booking_data(status: str | None = "created") -> BookingData:
    return BookingData(
        booking_id="book-123",
        start_time=datetime(2026, 1, 20, 10, 0, tzinfo=UTC),
        end_time=datetime(2026, 1, 20, 11, 0, tzinfo=UTC),
        status=status,
    )


class TestGetOrNone:
    @pytest.mark.anyio
    async def test_lifecycle_saver_queue_forces_upsert(self) -> None:
        """Lifecycle events carry status changes: get_or_none must return None to force upsert."""
        sql = FakeSqlExecutor(fetch_one_results=[{"id": 7}])
        repo = BookingRepository(sql)

        result = await repo.get_or_none(
            booking_id="book-123",
            queue_name=BOOKING_LIFECYCLE_SAVER_QUEUE.name,
        )

        assert result is None
        assert sql.queries == []  # short-circuits before any SQL

    @pytest.mark.anyio
    async def test_other_queue_returns_existing_booking(self) -> None:
        sql = FakeSqlExecutor(fetch_one_results=[{"id": 7}])
        repo = BookingRepository(sql)

        result = await repo.get_or_none(booking_id="book-123", queue_name="events.jitsi")

        assert result == 7

    @pytest.mark.anyio
    async def test_other_queue_returns_none_when_missing(self) -> None:
        sql = FakeSqlExecutor(fetch_one_results=[None])
        repo = BookingRepository(sql)

        result = await repo.get_or_none(booking_id="book-123", queue_name="events.jitsi")

        assert result is None


class TestUpsert:
    @pytest.mark.anyio
    async def test_returns_booking_id_and_passes_params(self) -> None:
        sql = FakeSqlExecutor(fetch_one_results=[{"id": 42}])
        repo = BookingRepository(sql)
        organizer = uuid.uuid4()

        result = await repo.upsert(
            booking_data=_booking_data(),
            occurred_at=_OCCURRED_AT,
            organizer_user_id=organizer,
            client_user_id=None,
        )

        assert result == 42
        query, params = sql.queries[0]
        assert "on conflict (booking_uid) do update" in query
        assert params["booking_uid"] == "book-123"
        assert params["current_status"] == "created"
        assert params["organizer_user_id"] == str(organizer)
        assert params["client_user_id"] is None

    @pytest.mark.anyio
    async def test_coalesce_keeps_existing_values_on_none(self) -> None:
        sql = FakeSqlExecutor(fetch_one_results=[{"id": 42}])
        repo = BookingRepository(sql)

        await repo.upsert(
            booking_data=BookingData(booking_id="book-123", start_time=None, end_time=None, status=None),
            occurred_at=_OCCURRED_AT,
            organizer_user_id=None,
            client_user_id=None,
        )

        query, params = sql.queries[0]
        assert "current_status = coalesce(excluded.current_status, bookings.current_status)" in query
        assert "start_time = coalesce(excluded.start_time, bookings.start_time)" in query
        assert params["current_status"] is None

    @pytest.mark.anyio
    async def test_raises_when_no_row_returned(self) -> None:
        sql = FakeSqlExecutor(fetch_one_results=[None])
        repo = BookingRepository(sql)

        with pytest.raises(RuntimeError, match="Failed to upsert booking"):
            await repo.upsert(
                booking_data=_booking_data(),
                occurred_at=_OCCURRED_AT,
                organizer_user_id=None,
                client_user_id=None,
            )


class TestSaveOrganizerHistory:
    @pytest.mark.anyio
    async def test_insert_is_deduplicated_against_latest_assignment(self) -> None:
        sql = FakeSqlExecutor()
        repo = BookingRepository(sql)
        organizer = uuid.uuid4()

        await repo.save_organizer_history(
            booking_id=42,
            organizer_user_id=organizer,
            source_event_id="evt-001",
            occurred_at=_OCCURRED_AT,
        )

        query, params = sql.queries[0]
        assert "is distinct from :organizer_user_id" in query
        assert params["organizer_user_id"] == str(organizer)
        assert params["booking_ref_id"] == 42


class TestUpdateClient:
    @pytest.mark.anyio
    async def test_sets_client_user_id(self) -> None:
        sql = FakeSqlExecutor()
        repo = BookingRepository(sql)
        client = uuid.uuid4()

        await repo.update_client(booking_ref_id=42, client_user_id=client)

        query, params = sql.queries[0]
        assert "update bookings" in query
        assert params == {"booking_ref_id": 42, "client_user_id": str(client)}
