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
