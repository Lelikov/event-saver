"""Periodic reconciliation of bookings whose participant user_ids were never resolved.

When event-users is down at ingress, event-receiver publishes participants with
user_id=None and event-saver persists bookings with NULL organizer_user_id /
client_user_id. This service re-resolves them: it selects a batch of incomplete
bookings, finds each missing participant's email in the latest stored event
payload (normalized.participants), asks event-users for the UUID by email+role,
and updates the booking row — all inside one transaction per cycle.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from event_saver.interfaces.user_resolver import UsersServiceUnavailableError


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from event_saver.interfaces.sql import ISqlExecutor, ISqlExecutorFactory
    from event_saver.interfaces.user_resolver import IUserResolver

logger = structlog.get_logger(__name__)

# role used in normalized.participants / event-users -> bookings column.
# Keys and values are a fixed allowlist: column names are interpolated into SQL
# from this mapping only, never from external input.
ROLE_COLUMNS: dict[str, str] = {
    "organizer": "organizer_user_id",
    "client": "client_user_id",
}

_SELECT_CANDIDATES = """
    SELECT id, booking_uid, organizer_user_id, client_user_id
    FROM bookings
    WHERE organizer_user_id IS NULL OR client_user_id IS NULL
    ORDER BY id
    LIMIT :batch_size
"""

# Latest non-empty participant email for the given role across the booking's
# stored events. The CASE guard keeps jsonb_array_elements from erroring on
# payloads where normalized.participants is missing or not an array.
_SELECT_LATEST_EMAIL = """
    SELECT participant->>'email' AS email
    FROM events e
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(e.payload->'normalized'->'participants') = 'array'
                THEN e.payload->'normalized'->'participants'
            ELSE '[]'::jsonb
        END
    ) AS participant
    WHERE e.booking_id = :booking_uid
      AND participant->>'role' = :role
      AND COALESCE(participant->>'email', '') <> ''
    ORDER BY e.occurred_at DESC
    LIMIT 1
"""

_UPDATE_TEMPLATE = """
    UPDATE bookings
    SET {column} = :user_id, updated_at = now()
    WHERE id = :id AND {column} IS NULL
"""


@dataclass(frozen=True, slots=True)
class BackfillSummary:
    """Outcome of a single backfill cycle (one participant slot = one unit)."""

    scanned_bookings: int = 0
    resolved: int = 0
    unresolved: int = 0
    missing_email: int = 0
    aborted: bool = False


class _Counters:
    """Mutable tally shared across the per-row helpers of one cycle."""

    def __init__(self) -> None:
        self.resolved = 0
        self.unresolved = 0
        self.missing_email = 0


class UserIdBackfillService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        sql_executor_factory: ISqlExecutorFactory,
        resolver: IUserResolver,
        batch_size: int,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._sql_executor_factory = sql_executor_factory
        self._resolver = resolver
        self._batch_size = batch_size

    async def run_once(self) -> BackfillSummary:
        """Run one reconciliation cycle; commits resolved rows even when aborting."""
        async with self._sessionmaker() as session:
            sql = self._sql_executor_factory(session)
            rows = await sql.fetch_all(_SELECT_CANDIDATES, {"batch_size": self._batch_size})

            counters = _Counters()
            cache: dict[tuple[str, str], uuid.UUID | None] = {}
            aborted = False
            try:
                for row in rows:
                    await self._backfill_row(sql, dict(row), counters, cache)
            except UsersServiceUnavailableError as exc:
                # Transport-level failure: keep what already resolved, skip the
                # rest of this cycle and let the next interval retry.
                logger.warning("event-users unavailable, skipping backfill cycle", error=str(exc))
                aborted = True

            await session.commit()
            return BackfillSummary(
                scanned_bookings=len(rows),
                resolved=counters.resolved,
                unresolved=counters.unresolved,
                missing_email=counters.missing_email,
                aborted=aborted,
            )

    async def _backfill_row(
        self,
        sql: ISqlExecutor,
        row: dict,
        counters: _Counters,
        cache: dict[tuple[str, str], uuid.UUID | None],
    ) -> None:
        for role, column in ROLE_COLUMNS.items():
            if row[column] is not None:
                continue
            await self._backfill_slot(sql, row, role=role, column=column, counters=counters, cache=cache)

    async def _backfill_slot(
        self,
        sql: ISqlExecutor,
        row: dict,
        *,
        role: str,
        column: str,
        counters: _Counters,
        cache: dict[tuple[str, str], uuid.UUID | None],
    ) -> None:
        email_row = await sql.fetch_one(
            _SELECT_LATEST_EMAIL,
            {"booking_uid": row["booking_uid"], "role": role},
        )
        if email_row is None:
            counters.missing_email += 1
            return

        email = email_row["email"]
        key = (email, role)
        if key not in cache:
            cache[key] = await self._resolver.resolve(email=email, role=role)

        user_id = cache[key]
        if user_id is None:
            counters.unresolved += 1
            logger.debug("No event-users match for participant", booking_uid=row["booking_uid"], role=role)
            return

        await sql.execute(
            _UPDATE_TEMPLATE.format(column=column),
            {"id": row["id"], "user_id": user_id},
        )
        counters.resolved += 1
        logger.info(
            "Backfilled participant user_id",
            booking_uid=row["booking_uid"],
            role=role,
            user_id=str(user_id),
        )
