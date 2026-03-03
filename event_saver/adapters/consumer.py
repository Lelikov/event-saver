from datetime import UTC, datetime
from typing import Any

import structlog
from cloudevents.http import from_http
from faststream import Context
from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitQueue

from event_saver.interfaces.consumer import IEventConsumerRunner
from event_saver.interfaces.event_store import IEventStore


logger = structlog.get_logger(__name__)


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
                queue=RabbitQueue(name=queue_name, durable=True, routing_key=queue_name),
                exchange=self._exchange,
            )

            @subscriber
            async def consume(message: Any = Context("message"), _queue_name: str = queue_name) -> None:
                await self._consume_message(message=message, queue_name=_queue_name)

        await self._broker.start()
        self._started = True
        logger.info("Rabbit consumer runner started", queue_count=len(self._queue_names))

    async def stop(self) -> None:
        if not self._started:
            return

        await self._broker.stop()
        self._started = False
        logger.info("Rabbit consumer runner stopped")

    async def _consume_message(self, *, message: Any, queue_name: str) -> None:
        event = from_http(headers=message.headers, data=message.body)

        await self._event_store.save_event(
            event_id=event["id"],
            booking_id=event.get("booking_id"),
            event_type=event["type"],
            source=event["source"],
            occurred_at=datetime.fromisoformat(event["time"]),
            payload=event.data,
        )
        logger.info(
            "Event consumed and saved",
            queue=queue_name,
            event_id=str(event["id"]),
            event_type=str(event["type"]),
        )