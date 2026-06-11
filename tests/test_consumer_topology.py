"""Contract tests: event-saver consumes the canonical per-consumer queues."""

from event_schemas.queues import SAVER_QUEUES, RoutingKey

from event_saver.adapters.consumer import RabbitEventConsumerRunner


class TestSaverQueueContract:
    def test_consumes_own_booking_lifecycle_queue(self) -> None:
        names = {q.name for q in SAVER_QUEUES}

        assert "events.booking.lifecycle.saver" in names
        assert "events.booking.lifecycle" not in names  # shared queue removed
        assert "events.booking.lifecycle.booking" not in names  # belongs to event-booking
        assert "events.booking.reminder" not in names  # queue removed entirely

    def test_lifecycle_queue_bound_to_lifecycle_routing_key(self) -> None:
        spec = next(q for q in SAVER_QUEUES if q.name == "events.booking.lifecycle.saver")

        assert spec.binding == RoutingKey.BOOKING_LIFECYCLE
        assert spec.arguments["x-dead-letter-exchange"] == "events.dlx"
        assert spec.arguments["x-max-priority"] == 10

    def test_runner_defaults_to_saver_queue_specs(self) -> None:
        runner = RabbitEventConsumerRunner(
            broker=object(),  # type: ignore[arg-type]
            exchange=object(),  # type: ignore[arg-type]
            event_store=object(),  # type: ignore[arg-type]
        )

        assert runner._queue_specs == SAVER_QUEUES  # noqa: SLF001
