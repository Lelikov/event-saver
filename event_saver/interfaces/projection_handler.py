from __future__ import annotations
import uuid
from typing import TYPE_CHECKING, Any, Protocol


if TYPE_CHECKING:
    from event_saver.domain.models.event import ParsedEvent


class IProjectionHandler(Protocol):
    def can_handle(self, event: ParsedEvent) -> bool: ...

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None: ...
