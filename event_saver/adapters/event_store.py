import hashlib
from datetime import datetime
from typing import Any

import ujson
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_saver.event_types import EventType, ParticipantRole, QueueName, SourceType
from event_saver.interfaces.event_store import IEventStore
from event_saver.interfaces.projection import IEventProjectionStatementFactory
from event_saver.interfaces.sql import ISqlExecutorFactory
from event_saver.utils import decode_user_id


class SqlEventStore(IEventStore):
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        projection_factory: IEventProjectionStatementFactory,
        sql_executor_factory: ISqlExecutorFactory,
        getstream_user_id_encryption_key: str | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._projection_factory = projection_factory
        self._sql_executor_factory = sql_executor_factory
        self._getstream_user_id_encryption_key = getstream_user_id_encryption_key

    async def save_event(
        self,
        *,
        queue_name: str,
        event_id: str,
        booking_id: str | None,
        event_type: str,
        source: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        async with self._sessionmaker() as session:
            sql = self._sql_executor_factory(session)
            payload_json = ujson.dumps(payload)

            is_inserted = await self._save_raw_event(
                sql=sql,
                event_id=event_id,
                booking_id=booking_id,
                event_type=event_type,
                source=source,
                occurred_at=occurred_at,
                payload_json=payload_json,
            )
            if not is_inserted or not booking_id:
                await session.commit()
                return

            organizer_ref_id, client_ref_id = await self._resolve_participants(
                sql=sql,
                source=source,
                payload=payload,
            )

            booking_ref_id = await self._save_booking(
                sql=sql,
                queue_name=queue_name,
                booking_id=booking_id,
                occurred_at=occurred_at,
                event_type=event_type,
                organizer_ref_id=organizer_ref_id,
                client_ref_id=client_ref_id,
            )
            if booking_ref_id is None:
                await session.commit()
                return

            if event_type in (EventType.BOOKING_CREATED, EventType.BOOKING_REASSIGNED):
                await self._save_organizer_history(
                    sql=sql,
                    booking_ref_id=booking_ref_id,
                    organizer_ref_id=organizer_ref_id,
                    source_event_id=event_id,
                    occurred_at=occurred_at,
                )

            await self._save_projections(
                sql=sql,
                queue_name=queue_name,
                booking_ref_id=booking_ref_id,
                organizer_ref_id=organizer_ref_id,
                client_ref_id=client_ref_id,
                event_id=event_id,
                source=source,
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
            )

            await session.commit()

    @staticmethod
    async def _save_raw_event(
        *,
        sql: Any,
        event_id: str,
        booking_id: str | None,
        event_type: str,
        source: str,
        occurred_at: datetime,
        payload_json: str,
    ) -> bool:
        row = await sql.fetch_one(
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
            returning event_id
            """,
            {
                "event_id": event_id,
                "booking_id": booking_id,
                "event_type": event_type,
                "source": source,
                "occurred_at": occurred_at,
                "payload": payload_json,
            },
        )
        return row is not None

    async def _resolve_participants(
        self,
        *,
        sql: Any,
        source: str,
        payload: dict[str, Any],
    ) -> tuple[int | None, int | None]:
        extracted = self._extract_event_participants(source=source, payload=payload)

        organizer_ref_id: int | None = None
        client_ref_id: int | None = None

        for participant in extracted:
            role = participant.get("role")
            participant_id = await self._upsert_participant(
                sql=sql,
                email=participant["email"],
                role=role,
                time_zone=participant.get("time_zone"),
            )

            if role == ParticipantRole.ORGANIZER:
                organizer_ref_id = participant_id
            if role == ParticipantRole.CLIENT:
                client_ref_id = participant_id

        return organizer_ref_id, client_ref_id

    def _extract_event_participants(
        self,
        *,
        source: str,
        payload: dict[str, Any],
    ) -> list[dict[str, str | None]]:
        participants: list[dict[str, str | None]] = []

        if source == SourceType.BOOKING:
            for user in payload.get("users") or []:
                email = user.get("email")
                role = user.get("role")
                time_zone = user.get("time_zone")

                participants.append({"email": email, "role": role, "time_zone": time_zone})

        if source == SourceType.UNISENDER_GO:
            participants.append({"email": payload.get("event_data", {}).get("email")})

        if source == SourceType.GETSTREAM:
            encoded_user_id = payload.get("user", {}).get("id")
            decoded = self._decode_user_id(encoded_user_id=encoded_user_id)
            participants.append({"email": decoded})

        if source == SourceType.JITSI:
            user = payload.get("context", {}).get("user", {})
            participants.append(
                {
                    "email": user.get("email"),
                    "role": user.get("role"),
                }
            )

        return participants

    def _decode_user_id(self, *, encoded_user_id: str) -> str:
        try:
            return decode_user_id(
                encoded_user_id=encoded_user_id,
                encryption_key=hashlib.sha256(self._getstream_user_id_encryption_key.encode()).digest(),
            )
        except Exception:
            return encoded_user_id

    async def _save_booking(
        self,
        *,
        sql: Any,
        queue_name: str,
        booking_id: str,
        occurred_at: datetime,
        event_type: str,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
    ) -> int | None:
        if queue_name != QueueName.EVENTS_BOOKING_LIFECYCLE:
            existing_row = await sql.fetch_one(
                """
                select id
                from bookings
                where booking_uid = :booking_uid
                limit 1
                """,
                {"booking_uid": booking_id},
            )
            return int(existing_row["id"]) if existing_row is not None else None

        row = await sql.fetch_one(
            """
            insert into bookings (
                booking_uid,
                first_seen_at,
                last_seen_at,
                current_status,
                current_organizer_participant_ref_id,
                current_client_participant_ref_id
            ) values (
                :booking_uid,
                :first_seen_at,
                :last_seen_at,
                :current_status,
                :current_organizer_participant_ref_id,
                :current_client_participant_ref_id
            )
            on conflict (booking_uid) do update
            set
                last_seen_at = greatest(bookings.last_seen_at, excluded.last_seen_at),
                current_status = coalesce(excluded.current_status, bookings.current_status),
                current_organizer_participant_ref_id = coalesce(
                    excluded.current_organizer_participant_ref_id,
                    bookings.current_organizer_participant_ref_id
                ),
                current_client_participant_ref_id = coalesce(
                    excluded.current_client_participant_ref_id,
                    bookings.current_client_participant_ref_id
                ),
                updated_at = now()
            returning id
            """,
            {
                "booking_uid": booking_id,
                "first_seen_at": occurred_at,
                "last_seen_at": occurred_at,
                "current_status": self._extract_booking_status(event_type=event_type),
                "current_organizer_participant_ref_id": organizer_ref_id,
                "current_client_participant_ref_id": client_ref_id,
            },
        )
        return int(row["id"]) if row is not None else None

    @staticmethod
    async def _save_organizer_history(
        *,
        sql: Any,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        source_event_id: str,
        occurred_at: datetime,
    ) -> None:
        if organizer_ref_id is None:
            return

        await sql.fetch_one(
            """
            insert into booking_organizer_history (
                booking_ref_id,
                organizer_participant_ref_id,
                source_event_id,
                effective_from
            )
            select
                :booking_ref_id,
                :organizer_participant_ref_id,
                :source_event_id,
                :effective_from
            where (
                (
                    select boh.organizer_participant_ref_id
                    from booking_organizer_history boh
                    where boh.booking_ref_id = :booking_ref_id
                    order by boh.effective_from desc, boh.id desc
                    limit 1
                ) is distinct from :organizer_participant_ref_id
            )
            returning id
            """,
            {
                "booking_ref_id": booking_ref_id,
                "organizer_participant_ref_id": organizer_ref_id,
                "source_event_id": source_event_id,
                "effective_from": occurred_at,
            },
        )

    async def _save_projections(
        self,
        *,
        sql: Any,
        queue_name: str,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        event_id: str,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> None:
        statements = self._projection_factory.build_projection_statements(
            queue_name=queue_name,
            booking_ref_id=booking_ref_id,
            organizer_ref_id=organizer_ref_id,
            client_ref_id=client_ref_id,
            event_id=event_id,
            source=source,
            event_type=event_type,
            payload=payload,
            occurred_at=occurred_at,
        )
        await sql.execute_in_transaction(statements)

    @staticmethod
    async def _upsert_participant(
        *,
        sql: Any,
        email: str | None,
        role: str | None,
        time_zone: str | None,
    ) -> int | None:
        if email is None:
            return None

        existing_row = await sql.fetch_one(
            """
            select id, role, time_zone
            from participants
            where email = :email
            limit 1
            """,
            {"email": email},
        )

        if existing_row is not None:
            existing_id = int(existing_row["id"])
            existing_role = existing_row["role"]
            existing_time_zone = existing_row["time_zone"]

            role_is_same_or_empty = role is None or role == existing_role
            time_zone_is_same_or_empty = time_zone is None or time_zone == existing_time_zone

            if role_is_same_or_empty and time_zone_is_same_or_empty:
                return existing_id

        row = await sql.fetch_one(
            """
            insert into participants (
                email,
                role,
                time_zone,
                updated_at
            ) values (
                :email,
                :role,
                :time_zone,
                now()
            )
            on conflict (email) do update
            set
                role = coalesce(excluded.role, participants.role),
                time_zone = coalesce(excluded.time_zone, participants.time_zone),
                updated_at = now()
            returning id
            """,
            {
                "email": email,
                "role": role,
                "time_zone": time_zone,
            },
        )
        return int(row["id"]) if row is not None else None

    @staticmethod
    def _extract_booking_status(event_type: str) -> str | None:
        if event_type == EventType.BOOKING_CREATED:
            return "created"
        if event_type == EventType.BOOKING_CANCELLED:
            return "cancelled"
        return None
