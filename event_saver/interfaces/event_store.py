from datetime import datetime
from typing import Any, Protocol


class IEventStore(Protocol):
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
    ) -> None: ...
