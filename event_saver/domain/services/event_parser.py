"""Domain service for parsing events into domain models."""

import hashlib
from datetime import UTC, datetime
from typing import Any

import ujson

from event_saver.domain.models.event import ParsedEvent, RawEventData


class EventParser:
    """Domain service for parsing raw event data.

    Pure business logic - no infrastructure dependencies.
    """

    @staticmethod
    def parse(
        *,
        event_id: str,
        event_type: str,
        source: str,
        time: Any,
        booking_id: str | None,
        data: dict[str, Any] | None,
    ) -> ParsedEvent:
        """Parse raw event attributes into domain model.

        Args:
            event_id: CloudEvent ID
            event_type: CloudEvent type
            source: CloudEvent source
            time: CloudEvent time (can be datetime or ISO string)
            booking_id: Optional booking identifier
            data: Event payload

        Returns:
            ParsedEvent with normalized data and computed hash

        """
        occurred_at = EventParser._parse_occurred_at(time)
        payload = data or {}
        payload_hash = EventParser._compute_payload_hash(payload)

        raw = RawEventData(
            event_id=event_id,
            event_type=event_type,
            source=source,
            occurred_at=occurred_at,
            booking_id=booking_id,
            payload=payload,
        )

        return ParsedEvent(raw=raw, payload_hash=payload_hash)

    @staticmethod
    def _parse_occurred_at(time_value: Any) -> datetime:
        """Parse occurred_at timestamp from various formats."""
        if time_value is None:
            return datetime.now(UTC)

        if isinstance(time_value, datetime):
            return time_value if time_value.tzinfo else time_value.replace(tzinfo=UTC)

        parsed = datetime.fromisoformat(str(time_value))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _compute_payload_hash(payload: dict[str, Any]) -> str:
        """Compute MD5 hash of payload for deduplication."""
        payload_json = ujson.dumps(payload)
        return hashlib.md5(payload_json.encode()).hexdigest()
