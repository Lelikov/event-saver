"""UserIdBackfillService: resolved / unresolved / missing-email / transport-error paths."""

import asyncio
import uuid
from typing import Any, Never, Self

import pytest

from event_saver.adapters.backfill_runner import UserIdBackfillRunner
from event_saver.application.services.user_id_backfill import BackfillSummary, UserIdBackfillService
from event_saver.interfaces.user_resolver import UsersServiceUnavailableError


ORGANIZER_ID = uuid.uuid4()
CLIENT_ID = uuid.uuid4()


class FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class FakeBackfillSql:
    """Returns canned candidate rows / participant emails; records UPDATEs."""

    def __init__(
        self,
        candidates: list[dict[str, Any]],
        emails: dict[tuple[str, str], str],
    ) -> None:
        self.candidates = candidates
        self.emails = emails
        self.updates: list[tuple[str, dict[str, Any]]] = []

    async def fetch_all(self, query: str, values: dict) -> list[dict[str, Any]]:  # noqa: ARG002
        assert values["batch_size"] > 0
        return self.candidates

    async def fetch_one(self, query: str, values: dict) -> dict[str, Any] | None:  # noqa: ARG002
        email = self.emails.get((values["booking_uid"], values["role"]))
        if email is None:
            return None
        return {"email": email}

    async def execute(self, query: str, values: dict) -> None:
        self.updates.append((query, values))


class FakeResolver:
    def __init__(
        self,
        users: dict[tuple[str, str], uuid.UUID] | None = None,
        unavailable: bool = False,
    ) -> None:
        self.users = users or {}
        self.unavailable = unavailable
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, *, email: str, role: str) -> uuid.UUID | None:
        self.calls.append((email, role))
        if self.unavailable:
            raise UsersServiceUnavailableError("event-users is down")
        return self.users.get((email, role))


def make_service(sql: FakeBackfillSql, resolver: FakeResolver, session: FakeSession) -> UserIdBackfillService:
    return UserIdBackfillService(
        sessionmaker=lambda: session,
        sql_executor_factory=lambda _session: sql,
        resolver=resolver,
        batch_size=100,
    )


def candidate(
    row_id: int = 1,
    booking_uid: str = "book-1",
    organizer: uuid.UUID | None = None,
    client: uuid.UUID | None = None,
) -> dict[str, Any]:
    return {
        "id": row_id,
        "booking_uid": booking_uid,
        "organizer_user_id": organizer,
        "client_user_id": client,
    }


@pytest.mark.anyio
async def test_resolves_both_missing_participants_and_commits() -> None:
    sql = FakeBackfillSql(
        candidates=[candidate()],
        emails={("book-1", "organizer"): "org@x.com", ("book-1", "client"): "cli@x.com"},
    )
    resolver = FakeResolver(users={("org@x.com", "organizer"): ORGANIZER_ID, ("cli@x.com", "client"): CLIENT_ID})
    session = FakeSession()

    summary = await make_service(sql, resolver, session).run_once()

    assert summary.scanned_bookings == 1
    assert summary.resolved == 2
    assert summary.unresolved == 0
    assert summary.missing_email == 0
    assert summary.aborted is False
    assert session.committed is True
    assert len(sql.updates) == 2
    organizer_update, client_update = sql.updates
    assert "organizer_user_id = :user_id" in organizer_update[0]
    assert organizer_update[1] == {"id": 1, "user_id": ORGANIZER_ID}
    assert "client_user_id = :user_id" in client_update[0]
    assert client_update[1] == {"id": 1, "user_id": CLIENT_ID}


@pytest.mark.anyio
async def test_only_missing_side_is_backfilled() -> None:
    sql = FakeBackfillSql(
        candidates=[candidate(organizer=ORGANIZER_ID)],
        emails={("book-1", "client"): "cli@x.com"},
    )
    resolver = FakeResolver(users={("cli@x.com", "client"): CLIENT_ID})
    session = FakeSession()

    summary = await make_service(sql, resolver, session).run_once()

    assert summary.resolved == 1
    assert resolver.calls == [("cli@x.com", "client")]
    assert len(sql.updates) == 1
    assert "client_user_id = :user_id" in sql.updates[0][0]


@pytest.mark.anyio
async def test_unknown_user_counts_as_unresolved_without_update() -> None:
    sql = FakeBackfillSql(
        candidates=[candidate(organizer=ORGANIZER_ID)],
        emails={("book-1", "client"): "ghost@x.com"},
    )
    resolver = FakeResolver(users={})
    session = FakeSession()

    summary = await make_service(sql, resolver, session).run_once()

    assert summary.resolved == 0
    assert summary.unresolved == 1
    assert sql.updates == []
    assert session.committed is True


@pytest.mark.anyio
async def test_missing_email_in_events_skips_resolution() -> None:
    sql = FakeBackfillSql(candidates=[candidate(organizer=ORGANIZER_ID)], emails={})
    resolver = FakeResolver()
    session = FakeSession()

    summary = await make_service(sql, resolver, session).run_once()

    assert summary.missing_email == 1
    assert resolver.calls == []
    assert sql.updates == []


@pytest.mark.anyio
async def test_transport_error_aborts_cycle_but_keeps_prior_updates() -> None:
    first = candidate(row_id=1, booking_uid="book-1", organizer=ORGANIZER_ID)
    second = candidate(row_id=2, booking_uid="book-2", organizer=ORGANIZER_ID)
    sql = FakeBackfillSql(
        candidates=[first, second],
        emails={("book-1", "client"): "cli@x.com", ("book-2", "client"): "other@x.com"},
    )

    class FlakyResolver(FakeResolver):
        async def resolve(self, *, email: str, role: str) -> uuid.UUID | None:
            self.calls.append((email, role))
            if email == "other@x.com":
                raise UsersServiceUnavailableError("event-users is down")
            return CLIENT_ID

    resolver = FlakyResolver()
    session = FakeSession()

    summary = await make_service(sql, resolver, session).run_once()

    assert summary.aborted is True
    assert summary.resolved == 1
    assert len(sql.updates) == 1
    assert session.committed is True


@pytest.mark.anyio
async def test_same_identity_is_resolved_once_per_cycle() -> None:
    rows = [
        candidate(row_id=1, booking_uid="book-1", organizer=ORGANIZER_ID),
        candidate(row_id=2, booking_uid="book-2", organizer=ORGANIZER_ID),
    ]
    sql = FakeBackfillSql(
        candidates=rows,
        emails={("book-1", "client"): "cli@x.com", ("book-2", "client"): "cli@x.com"},
    )
    resolver = FakeResolver(users={("cli@x.com", "client"): CLIENT_ID})
    session = FakeSession()

    summary = await make_service(sql, resolver, session).run_once()

    assert summary.resolved == 2
    assert resolver.calls == [("cli@x.com", "client")]


class RecordingService:
    def __init__(self) -> None:
        self.runs = 0
        self.first_run = asyncio.Event()

    async def run_once(self) -> BackfillSummary:
        self.runs += 1
        self.first_run.set()
        return BackfillSummary()


@pytest.mark.anyio
async def test_runner_disabled_never_runs() -> None:
    service = RecordingService()
    runner = UserIdBackfillRunner(service=service, interval_seconds=0.01, enabled=False)

    await runner.start()
    await asyncio.sleep(0.05)
    await runner.stop()

    assert service.runs == 0


@pytest.mark.anyio
async def test_runner_enabled_runs_and_stops_cleanly() -> None:
    service = RecordingService()
    runner = UserIdBackfillRunner(service=service, interval_seconds=60.0, enabled=True)

    await runner.start()
    await asyncio.wait_for(service.first_run.wait(), timeout=1.0)
    await runner.stop()

    assert service.runs == 1
    # a second stop call must be a no-op
    await runner.stop()


@pytest.mark.anyio
async def test_runner_survives_cycle_exceptions() -> None:
    class ExplodingService:
        def __init__(self) -> None:
            self.runs = 0
            self.second_run = asyncio.Event()

        async def run_once(self) -> Never:
            self.runs += 1
            if self.runs >= 2:
                self.second_run.set()
            raise RuntimeError("boom")

    service = ExplodingService()
    runner = UserIdBackfillRunner(service=service, interval_seconds=0.01, enabled=True)

    await runner.start()
    await asyncio.wait_for(service.second_run.wait(), timeout=1.0)
    await runner.stop()

    assert service.runs >= 2
