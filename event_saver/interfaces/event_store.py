from datetime import datetime
from typing import Any, Protocol


class IEventStore(Protocol):
    async def save_event(
        self,
        *,
        event_id: str,
        booking_id: str,
        event_type: str,
        source: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> None: ...
