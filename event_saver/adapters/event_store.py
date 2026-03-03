from datetime import datetime
from typing import Any

import ujson
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_saver.adapters.sql import SqlExecutor
from event_saver.interfaces.event_store import IEventStore


class SqlEventStore(IEventStore):
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def save_event(
        self,
        *,
        event_id: str,
        booking_id: str,
        event_type: str,
        source: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        async with self._sessionmaker() as session:
            await SqlExecutor(session).execute(
                """
                insert into events (
                    event_id,
                    booking_id,
                    event_type,
                    source,
                    hash,
                    occurred_at,
                    payload
                ) values (
                    :event_id,
                    :booking_id,
                    :event_type,
                    :source,
                    md5(cast(:payload as jsonb)::text),
                    :occurred_at,
                    cast(:payload as jsonb)
                )
                on conflict (booking_id, event_type, source, hash) do nothing
                """,
                {
                    "event_id": event_id,
                    "booking_id": booking_id,
                    "event_type": event_type,
                    "source": source,
                    "occurred_at": occurred_at,
                    "payload": ujson.dumps(payload),
                },
            )
