from datetime import UTC, datetime
from typing import Any

import structlog
from cloudevents.http import from_http
from faststream import Context
from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitQueue

from event_saver.interfaces.consumer import IEventConsumerRunner
from event_saver.interfaces.event_store import IEventStore


logger = structlog.get_logger(__name__)


def _extract_extension(event: dict[str, Any], key: str) -> str | None:
    """Extract CloudEvents extension field."""
    return event.get(key)


def _parse_occurred_at(time_value: Any) -> datetime:
    if time_value is None:
        return datetime.now(UTC)

    if isinstance(time_value, datetime):
        return time_value if time_value.tzinfo else time_value.replace(tzinfo=UTC)

    parsed = datetime.fromisoformat(str(time_value))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class RabbitEventConsumerRunner(IEventConsumerRunner):
    def __init__(
        self,
        *,
        broker: RabbitBroker,
        exchange: RabbitExchange,
        queue_names: set[str],
        event_store: IEventStore,
    ) -> None:
        self._broker = broker
        self._exchange = exchange
        self._queue_names = queue_names
        self._event_store = event_store
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        for queue_name in self._queue_names:
            subscriber = self._broker.subscriber(
                queue=RabbitQueue(
                    name=queue_name,
                    durable=True,
                    routing_key=queue_name,
                ),
                exchange=self._exchange,
            )

            @subscriber
            async def consume(
                message: Any = Context("message"),
                _queue_name: str = queue_name,
            ) -> None:
                await self._consume_message(message=message, queue_name=_queue_name)

        await self._broker.start()
        self._started = True
        logger.info(
            "Rabbit consumer runner started",
            queue_count=len(self._queue_names),
        )

    async def stop(self) -> None:
        if not self._started:
            return

        await self._broker.stop()
        self._started = False
        logger.info("Rabbit consumer runner stopped")

    async def _consume_message(self, *, message: Any, queue_name: str) -> None:
        try:
            event = from_http(headers=message.headers, data=message.body)
        except Exception:
            logger.exception(
                "Failed to parse CloudEvent from message",
                queue=queue_name,
            )
            raise

        event_id = event["id"]
        event_type = event["type"]
        source = event["source"]
        booking_id = event.get("booking_id")
        occurred_at = _parse_occurred_at(event["time"])

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
            await self._event_store.save_event(
                queue_name=queue_name,
                event_id=event_id,
                booking_id=booking_id,
                event_type=event_type,
                source=source,
                occurred_at=occurred_at,
                payload=event.data or {},
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                span_id=span_id,
                dataschema=dataschema,
            )
        except Exception:
            logger.exception(
                "Failed to save event to store",
                queue=queue_name,
                event_id=event_id,
                event_type=event_type,
                source=source,
                booking_id=booking_id,
                trace_id=trace_id,
            )
            raise
        finally:
            # Clear context after processing
            if trace_id:
                structlog.contextvars.clear_contextvars()

        logger.info(
            "Event consumed and saved",
            queue=queue_name,
            event_id=event_id,
            event_type=event_type,
            booking_id=booking_id,
            trace_id=trace_id,
        )
