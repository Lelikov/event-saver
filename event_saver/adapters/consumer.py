from typing import Any

import structlog
from cloudevents.http import from_http
from event_schemas.attributes import BOOKING_ID_ATTRIBUTE
from event_schemas.queues import EVENTS_DLX, SAVER_QUEUES, QueueSpec
from faststream import Context
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from event_saver.interfaces.consumer import IEventConsumerRunner
from event_saver.interfaces.event_store import IEventStore


logger = structlog.get_logger(__name__)


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
    ) -> None:
        self._broker = broker
        self._exchange = exchange
        self._queue_specs = queue_specs
        self._event_store = event_store
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

            @subscriber
            async def consume(
                message: Any = Context("message"),
                _queue_name: str = spec.name,
            ) -> None:
                await self._consume_message(message=message, queue_name=_queue_name)

        await self._broker.start()
        await self._ensure_dead_letter_topology()
        self._started = True
        logger.info(
            "Rabbit consumer runner started",
            queue_count=len(self._queue_specs),
        )

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
            await self._event_store.save_event(
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
