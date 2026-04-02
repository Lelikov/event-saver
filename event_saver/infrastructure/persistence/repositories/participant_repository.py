"""Repository for participant persistence - pure CRUD operations."""

from event_saver.domain.models.participant import Participant
from event_saver.interfaces.sql import ISqlExecutor


class ParticipantRepository:
    """Repository for participants table.

    Handles only data persistence - no business logic.
    """

    def __init__(self, sql: ISqlExecutor) -> None:
        self._sql = sql

    async def upsert(self, participant: Participant) -> int:
        """Insert or update participant.

        Returns participant ID (internal database key).
        Updates role and timezone if new values provided.
        """
        row = await self._sql.fetch_one(
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
                "email": participant.email,
                "role": participant.role,
                "time_zone": participant.time_zone,
            },
        )

        if row is None:
            msg = f"Failed to upsert participant: {participant.email}"
            raise RuntimeError(msg)

        return int(row["id"])

    async def find_by_email(self, email: str) -> tuple[int, Participant] | None:
        """Find participant by email.

        Returns tuple of (id, participant) or None if not found.
        """
        row = await self._sql.fetch_one(
            """
            select id, email, role, time_zone
            from participants
            where email = :email
            limit 1
            """,
            {"email": email},
        )

        if row is None:
            return None

        participant = Participant(
            email=row["email"],
            role=row["role"],
            time_zone=row["time_zone"],
        )

        return int(row["id"]), participant

    async def upsert_if_changed(self, participant: Participant) -> int:
        """Upsert participant only if data has changed.

        Optimized version that checks existing data first.
        Returns participant ID.
        """
        existing = await self.find_by_email(participant.email)

        if existing is not None:
            existing_id, existing_participant = existing

            # Check if update needed
            role_same_or_empty = participant.role is None or participant.role == existing_participant.role
            tz_same_or_empty = (
                participant.time_zone is None or participant.time_zone == existing_participant.time_zone
            )

            if role_same_or_empty and tz_same_or_empty:
                return existing_id

        # Insert or update
        return await self.upsert(participant)
