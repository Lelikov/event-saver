"""Domain models for events - pure value objects with no external dependencies."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RawEventData:
    """Raw event data extracted from CloudEvent - immutable value object."""

    event_id: str
    event_type: str
    source: str
    occurred_at: datetime
    booking_id: str | None
    payload: dict[str, Any]
    # CloudEvents extensions for tracing and deduplication
    idempotency_key: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    dataschema: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedEvent:
    """Parsed event ready for processing.

    Contains both raw data and computed hash for deduplication.
    """

    raw: RawEventData
    payload_hash: str

    @property
    def event_id(self) -> str:
        return self.raw.event_id

    @property
    def event_type(self) -> str:
        return self.raw.event_type

    @property
    def source(self) -> str:
        return self.raw.source

    @property
    def occurred_at(self) -> datetime:
        return self.raw.occurred_at

    @property
    def booking_id(self) -> str | None:
        return self.raw.booking_id

    @property
    def payload(self) -> dict[str, Any]:
        return self.raw.payload

    @property
    def idempotency_key(self) -> str | None:
        return self.raw.idempotency_key

    @property
    def trace_id(self) -> str | None:
        return self.raw.trace_id

    @property
    def span_id(self) -> str | None:
        return self.raw.span_id

    @property
    def dataschema(self) -> str | None:
        return self.raw.dataschema
