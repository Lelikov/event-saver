from __future__ import annotations
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from event_saver.domain.models.booking import BookingData
    from event_saver.domain.models.event import ParsedEvent


class IEventRepository(Protocol):
    async def save(self, event: ParsedEvent) -> bool: ...


class IBookingRepository(Protocol):
    async def get_or_none(self, *, booking_id: str, queue_name: str) -> int | None: ...

    async def upsert(
        self,
        *,
        booking_data: BookingData,
        occurred_at: datetime,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
    ) -> int: ...

    async def update_client(
        self,
        *,
        booking_ref_id: int,
        client_user_id: uuid.UUID,
    ) -> None: ...

    async def backfill_user_id_by_email(self, email: str, role: str, user_id: uuid.UUID) -> None: ...

    async def save_organizer_history(
        self,
        *,
        booking_id: int,
        organizer_user_id: uuid.UUID,
        source_event_id: str,
        occurred_at: datetime,
    ) -> None: ...
