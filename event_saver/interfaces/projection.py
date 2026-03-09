from datetime import datetime
from typing import Any, Protocol


class IBookingEventClassifier(Protocol):
    def extract_action(
        self,
        *,
        queue_name: str,
        event_type: str,
        source: str,
        payload: dict[str, Any],
    ) -> str: ...


class IEventProjectionStatementFactory(Protocol):
    def build_projection_statements(
        self,
        *,
        queue_name: str,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        event_id: str,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> list[tuple[str, dict[str, Any]]]: ...