from datetime import UTC, datetime
from typing import Any


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 string (with optional trailing Z) into a timezone-aware datetime."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None
