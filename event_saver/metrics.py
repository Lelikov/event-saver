"""Prometheus metrics for event-saver.

Module-level metric objects (idiomatic for prometheus-client). Consumer RED
metrics are recorded by the RabbitMQ consumer; business counters by the ingest
use case and projections. Exposed via GET /metrics on the health HTTP app.
"""

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response


MESSAGES_PROCESSED_TOTAL = Counter(
    "messages_processed_total",
    "Consumed RabbitMQ messages by queue, event type and outcome (ok, retried, rejected).",
    ["queue", "event_type", "outcome"],
)
MESSAGE_PROCESSING_SECONDS = Histogram(
    "message_processing_seconds",
    "Message processing duration in seconds by queue.",
    ["queue"],
)

EVENTS_TOTAL = Counter(
    "saver_events_total",
    "Raw events persisted (deduplicated inserts) by event type.",
    ["event_type"],
)
BOOKING_LIFECYCLE_TOTAL = Counter(
    "saver_booking_lifecycle_total",
    "Booking status transitions projected to booking_lifecycle_events, by action.",
    ["action"],
)


def record_message(*, queue: str, event_type: str, outcome: str, started_at: float) -> None:
    MESSAGES_PROCESSED_TOTAL.labels(queue=queue, event_type=event_type, outcome=outcome).inc()
    MESSAGE_PROCESSING_SECONDS.labels(queue=queue).observe(time.perf_counter() - started_at)


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
