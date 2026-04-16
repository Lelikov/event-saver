"""Base class for projection handlers."""

import uuid
from abc import ABC, abstractmethod
from typing import Any

from event_saver.domain.models.event import ParsedEvent


class BaseProjection(ABC):
    """Base class for event projection handlers."""

    @abstractmethod
    def can_handle(self, event: ParsedEvent) -> bool:
        """Check if this projection can handle the event."""
        ...

    @abstractmethod
    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        """Handle the event and return SQL statement to execute.

        Returns:
            Tuple of (sql, params) or None if nothing to project

        """
        ...
