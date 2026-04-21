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
        time: Any,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        dataschema: str | None = None,
    ) -> None: ...
