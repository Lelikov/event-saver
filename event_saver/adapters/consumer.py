import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

import structlog
from cloudevents.http import from_http
from event_schemas.attributes import BOOKING_ID_ATTRIBUTE
from event_schemas.queues import EVENTS_DLX, SAVER_QUEUES, QueueSpec
from faststream import Context
from faststream.exceptions import NackMessage, RejectMessage
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as SqlTimeoutError

from event_saver import metrics
from event_saver.interfaces.consumer import IEventConsumerRunner
from event_saver.interfaces.event_store import IEventStore


logger = structlog.get_logger(__name__)

DEFAULT_TRANSIENT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 0.5

_TRANSIENT_ERROR_TYPES = (
    OperationalError,  # DB connectivity / restart
    InterfaceError,  # driver-level connection failure
    SqlTimeoutError,  # connection pool exhaustion
    OSError,  # network errors (includes ConnectionError)
    TimeoutError,  # asyncio timeouts
)


def _is_transient(exc: BaseException) -> bool:
    """Classify an exception as retryable infrastructure failure (vs poison message)."""
    if isinstance(exc, _TRANSIENT_ERROR_TYPES):
        return True
    return isinstance(exc, DBAPIError) and exc.connection_invalidated


def _extract_extension(event: dict[str, Any], key: str) -> str | None:
    """Extract CloudEvents extension field."""
    return event.get(key)


class RabbitEventConsumerRunner(IEventConsumerRunner):
    def __init__(
        self,
        *,
        broker: RabbitBroker,
        exchange: RabbitExchange,
        event_store: IEventStore,
        queue_specs: tuple[QueueSpec, ...] = SAVER_QUEUES,
        transient_retry_attempts: int = DEFAULT_TRANSIENT_RETRY_ATTEMPTS,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    ) -> None:
        self._broker = broker
        self._exchange = exchange
        self._queue_specs = queue_specs
        self._event_store = event_store
        self._transient_retry_attempts = transient_retry_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        for spec in self._queue_specs:
            subscriber = self._broker.subscriber(
                queue=RabbitQueue(
                    name=spec.name,
                    durable=True,
                    routing_key=str(spec.binding),
                    declare=True,
                    arguments=spec.arguments,
                ),
                exchange=self._exchange,
            )
            subscriber(self._make_handler(spec.name))

        await self._broker.start()
        await self._ensure_dead_letter_topology()
        self._started = True
        logger.info(
            "Rabbit consumer runner started",
            queue_count=len(self._queue_specs),
        )

    def _make_handler(self, queue_name: str) -> Callable[..., Awaitable[None]]:
        """Build a per-queue handler with the queue name captured in a closure.

        The closure keeps the queue name out of the handler signature, so
        FastStream cannot mistake it for a message-body field (a payload with
        a same-named top-level key must never override the consuming queue).
        """

        async def consume(message: Any = Context("message")) -> None:  # noqa: B008
            await self._consume_message(message=message, queue_name=queue_name)

        return consume

    async def _ensure_dead_letter_topology(self) -> None:
        """Idempotently declare the DLX and own DLQs (no startup-order dependency on event-receiver)."""
        dlx = RabbitExchange(name=EVENTS_DLX, type=ExchangeType.TOPIC, durable=True)
        declared_dlx = await self._broker.declare_exchange(dlx)
        for spec in self._queue_specs:
            dlq = RabbitQueue(
                name=spec.dlq_name,
                durable=True,
                routing_key=spec.dlq_name,
                arguments=spec.dlq_arguments,
            )
            declared_dlq = await self._broker.declare_queue(dlq)
            await declared_dlq.bind(exchange=declared_dlx, routing_key=spec.dlq_name)
        logger.info("Dead-letter topology ensured", dlx=EVENTS_DLX, dlq_count=len(self._queue_specs))

    async def stop(self) -> None:
        if not self._started:
            return

        await self._broker.stop()
        self._started = False
        logger.info("Rabbit consumer runner stopped")

    async def _consume_message(self, *, message: Any, queue_name: str) -> None:
        started_at = perf_counter()
        try:
            event = from_http(headers=message.headers, data=message.body)
        except Exception as exc:
            metrics.record_message(queue=queue_name, event_type="unknown", outcome="rejected", started_at=started_at)
            logger.exception(
                "Failed to parse CloudEvent from message: poison, dead-lettering",
                queue=queue_name,
            )
            raise RejectMessage from exc

        event_id = event["id"]
        event_type = event["type"]
        source = event["source"]
        booking_id = event.get(BOOKING_ID_ATTRIBUTE)
        time = event["time"]

        # Extract CloudEvents extensions
        idempotency_key = _extract_extension(event, "idempotencykey")
        trace_id = _extract_extension(event, "traceid")
        span_id = _extract_extension(event, "spanid")
        dataschema = _extract_extension(event, "dataschema")

        # Bind trace_id to structlog context for all subsequent logs
        if trace_id:
            structlog.contextvars.bind_contextvars(
                trace_id=trace_id,
                span_id=span_id,
            )

        try:
            await self._save_with_retry(
                queue_name=queue_name,
                event_id=event_id,
                booking_id=booking_id,
                event_type=event_type,
                source=source,
                time=time,
                payload=event.data or {},
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                span_id=span_id,
                dataschema=dataschema,
            )
        except NackMessage:
            metrics.record_message(queue=queue_name, event_type=event_type, outcome="retried", started_at=started_at)
            raise
        except RejectMessage:
            metrics.record_message(queue=queue_name, event_type=event_type, outcome="rejected", started_at=started_at)
            raise
        finally:
            # Clear context after processing
            if trace_id:
                structlog.contextvars.clear_contextvars()

        metrics.record_message(queue=queue_name, event_type=event_type, outcome="ok", started_at=started_at)
        logger.info(
            "Event consumed and saved",
            queue=queue_name,
            event_id=event_id,
            event_type=event_type,
            booking_id=booking_id,
            trace_id=trace_id,
        )

    async def _save_with_retry(self, **save_kwargs: Any) -> None:
        """Save the event, retrying transient infrastructure failures with backoff.

        - Transient errors (DB connectivity, pool/network timeouts) are retried
          in-process; once attempts are exhausted the message is NACKed with
          requeue so it is redelivered instead of being dead-lettered and lost.
        - Any other exception is a poison message and is rejected to the DLQ.
        """
        last_error: BaseException | None = None

        for attempt in range(1, self._transient_retry_attempts + 1):
            last_error = await self._attempt_save(save_kwargs)
            if last_error is None:
                return

            logger.warning(
                "Transient failure saving event, retrying",
                attempt=attempt,
                max_attempts=self._transient_retry_attempts,
                error=str(last_error),
                event_id=save_kwargs.get("event_id"),
                queue=save_kwargs.get("queue_name"),
            )
            if attempt < self._transient_retry_attempts:
                await asyncio.sleep(self._retry_backoff_seconds * 2 ** (attempt - 1))

        logger.error(
            "Transient retries exhausted, requeueing message",
            event_id=save_kwargs.get("event_id"),
            queue=save_kwargs.get("queue_name"),
        )
        raise NackMessage(requeue=True) from last_error

    async def _attempt_save(self, save_kwargs: dict[str, Any]) -> BaseException | None:
        """Run one save attempt; return the transient error, reject poison, None on success."""
        try:
            await self._event_store.save_event(**save_kwargs)
        except Exception as exc:
            if not _is_transient(exc):
                logger.exception(
                    "Non-transient failure saving event: poison, dead-lettering",
                    event_id=save_kwargs.get("event_id"),
                    event_type=save_kwargs.get("event_type"),
                    queue=save_kwargs.get("queue_name"),
                )
                raise RejectMessage from exc
            return exc
        return None
