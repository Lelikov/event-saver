"""Tests for IngestEventUseCase orchestration with fake repositories."""

import uuid
from typing import Any

import pytest
from event_schemas.queues import BOOKING_LIFECYCLE_SAVER_QUEUE

from event_saver.application.use_cases.ingest_event import IngestEventUseCase
from event_saver.domain.models.booking import BookingData
from event_saver.domain.services import BookingDataExtractor, EventParser, ParticipantExtractor


_LIFECYCLE_QUEUE = BOOKING_LIFECYCLE_SAVER_QUEUE.name


class FakeEventRepository:
    def __init__(self, inserted: bool = True) -> None:
        self.inserted = inserted
        self.saved_events: list[Any] = []

    async def save(self, event: Any) -> bool:
        self.saved_events.append(event)
        return self.inserted


class FakeBookingRepository:
    def __init__(self, existing_booking_id: int | None = None) -> None:
        self.existing_booking_id = existing_booking_id
        self.upserts: list[dict[str, Any]] = []
        self.organizer_history: list[dict[str, Any]] = []
        self.client_updates: list[dict[str, Any]] = []
        self.backfill_calls: list[tuple[str, str, uuid.UUID]] = []

    async def get_or_none(self, *, booking_id: str, queue_name: str) -> int | None:  # noqa: ARG002
        if queue_name == _LIFECYCLE_QUEUE:
            return None
        return self.existing_booking_id

    async def upsert(
        self,
        *,
        booking_data: BookingData,
        occurred_at: Any,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
    ) -> int:
        self.upserts.append(
            {
                "booking_data": booking_data,
                "occurred_at": occurred_at,
                "organizer_user_id": organizer_user_id,
                "client_user_id": client_user_id,
            },
        )
        return 42

    async def update_client(self, *, booking_ref_id: int, client_user_id: uuid.UUID) -> None:
        self.client_updates.append({"booking_ref_id": booking_ref_id, "client_user_id": client_user_id})

    async def save_organizer_history(self, **kwargs: Any) -> None:
        self.organizer_history.append(kwargs)

    async def backfill_user_id_by_email(self, email: str, role: str, user_id: uuid.UUID) -> None:
        self.backfill_calls.append((email, role, user_id))


class FakeProjectionExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute_projections(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _use_case(
    event_repo: FakeEventRepository,
    booking_repo: FakeBookingRepository,
    projections: FakeProjectionExecutor,
) -> IngestEventUseCase:
    return IngestEventUseCase(
        event_parser=EventParser(),
        participant_extractor=ParticipantExtractor(),
        booking_data_extractor=BookingDataExtractor(),
        event_repository=event_repo,
        booking_repository=booking_repo,
        projection_executor=projections,
    )


def _execute_kwargs(**overrides: Any) -> dict[str, Any]:
    organizer = overrides.pop("organizer_id", str(uuid.uuid4()))
    client = overrides.pop("client_id", str(uuid.uuid4()))
    kwargs: dict[str, Any] = {
        "queue_name": _LIFECYCLE_QUEUE,
        "event_id": "evt-001",
        "event_type": "booking.created",
        "source": "booking",
        "time": "2026-01-15T10:00:00+00:00",
        "booking_id": "book-123",
        "data": {
            "original": {"start_time": "2026-01-20T10:00:00Z", "end_time": "2026-01-20T11:00:00Z"},
            "normalized": {
                "participants": [
                    {"role": "organizer", "user_id": organizer},
                    {"role": "client", "user_id": client},
                ],
            },
        },
        "idempotency_key": "idem-1",
    }
    kwargs.update(overrides)
    return kwargs


class TestDuplicateSkip:
    @pytest.mark.anyio
    async def test_duplicate_event_skips_booking_and_projections(self) -> None:
        event_repo = FakeEventRepository(inserted=False)
        booking_repo = FakeBookingRepository()
        projections = FakeProjectionExecutor()

        await _use_case(event_repo, booking_repo, projections).execute(**_execute_kwargs())

        assert len(event_repo.saved_events) == 1
        assert booking_repo.upserts == []
        assert projections.calls == []


class TestNoBookingId:
    @pytest.mark.anyio
    async def test_event_without_booking_id_only_saves_raw_event(self) -> None:
        event_repo = FakeEventRepository()
        booking_repo = FakeBookingRepository()
        projections = FakeProjectionExecutor()

        await _use_case(event_repo, booking_repo, projections).execute(
            **_execute_kwargs(booking_id=None, queue_name="events.unrouted"),
        )

        assert len(event_repo.saved_events) == 1
        assert booking_repo.upserts == []
        assert projections.calls == []


class TestLifecycleFlow:
    @pytest.mark.anyio
    async def test_booking_created_upserts_and_saves_organizer_history(self) -> None:
        organizer = str(uuid.uuid4())
        event_repo = FakeEventRepository()
        booking_repo = FakeBookingRepository()
        projections = FakeProjectionExecutor()

        await _use_case(event_repo, booking_repo, projections).execute(
            **_execute_kwargs(organizer_id=organizer),
        )

        assert len(booking_repo.upserts) == 1
        upsert = booking_repo.upserts[0]
        assert upsert["booking_data"].status == "created"
        assert str(upsert["organizer_user_id"]) == organizer
        assert len(booking_repo.organizer_history) == 1
        assert len(projections.calls) == 1
        assert projections.calls[0]["booking_ref_id"] == 42

    @pytest.mark.anyio
    async def test_existing_booking_on_other_queue_skips_upsert(self) -> None:
        event_repo = FakeEventRepository()
        booking_repo = FakeBookingRepository(existing_booking_id=7)
        projections = FakeProjectionExecutor()

        await _use_case(event_repo, booking_repo, projections).execute(
            **_execute_kwargs(queue_name="events.jitsi", event_type="jitsi.conference_joined"),
        )

        assert booking_repo.upserts == []
        assert projections.calls[0]["booking_ref_id"] == 7


class TestClientReassigned:
    @pytest.mark.anyio
    async def test_updates_client_and_propagates_to_projections(self) -> None:
        new_client = str(uuid.uuid4())
        event_repo = FakeEventRepository()
        booking_repo = FakeBookingRepository()
        projections = FakeProjectionExecutor()

        kwargs = _execute_kwargs(event_type="booking.client_reassigned")
        kwargs["data"]["original"]["new_client_user_id"] = new_client

        await _use_case(event_repo, booking_repo, projections).execute(**kwargs)

        assert len(booking_repo.client_updates) == 1
        assert str(booking_repo.client_updates[0]["client_user_id"]) == new_client
        assert str(projections.calls[0]["client_user_id"]) == new_client

    @pytest.mark.anyio
    async def test_invalid_new_client_uuid_is_ignored(self) -> None:
        event_repo = FakeEventRepository()
        booking_repo = FakeBookingRepository()
        projections = FakeProjectionExecutor()

        kwargs = _execute_kwargs(event_type="booking.client_reassigned")
        kwargs["data"]["original"]["new_client_user_id"] = "not-a-uuid"

        await _use_case(event_repo, booking_repo, projections).execute(**kwargs)

        assert booking_repo.client_updates == []


class TestUserSynced:
    @pytest.mark.anyio
    async def test_backfills_user_id_by_email_and_skips_booking_flow(self) -> None:
        user_id = str(uuid.uuid4())
        event_repo = FakeEventRepository()
        booking_repo = FakeBookingRepository()
        projections = FakeProjectionExecutor()

        await _use_case(event_repo, booking_repo, projections).execute(
            **_execute_kwargs(
                queue_name="events.user.synced",
                event_type="user.synced",
                source="event-users",
                booking_id=None,
                data={
                    "original": {
                        "email": "c@ex.com",
                        "role": "client",
                        "user_id": user_id,
                        "time_zone": "UTC",
                    },
                    "normalized": {"participants": []},
                },
            ),
        )

        assert booking_repo.backfill_calls == [("c@ex.com", "client", uuid.UUID(user_id))]
        assert booking_repo.upserts == []
        assert projections.calls == []
        assert len(event_repo.saved_events) == 1
