"""Tests for /metrics exposition and consumer RED counters."""

import pytest
from faststream.exceptions import NackMessage, RejectMessage
from prometheus_client import REGISTRY

from event_saver import main
from event_saver.infrastructure.persistence.projections.lifecycle_projection import LifecycleProjection
from tests.adapters.test_consumer import (
    FakeEventStore,
    FakeMessage,
    _cloud_event_message,
    _runner,
    _transient_error,
)
from tests.application.test_ingest_event import (
    FakeBookingRepository,
    FakeEventRepository,
    FakeProjectionExecutor,
    _execute_kwargs,
    _use_case,
)


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestMetricsEndpoint:
    def test_metrics_route_registered(self) -> None:
        paths = {route.path for route in main.app.routes}

        assert "/metrics" in paths

    @pytest.mark.anyio
    async def test_metrics_returns_prometheus_exposition(self) -> None:
        response = await main.metrics_endpoint()

        assert response.status_code == 200
        assert response.media_type.startswith("text/plain")
        assert b"messages_processed_total" in response.body


class TestConsumerRedMetrics:
    @pytest.mark.anyio
    async def test_ok_outcome_and_duration_recorded(self) -> None:
        runner = _runner(FakeEventStore())
        labels = {"queue": "events.jitsi", "event_type": "booking.created", "outcome": "ok"}
        before = _sample("messages_processed_total", labels)
        duration_before = _sample("message_processing_seconds_count", {"queue": "events.jitsi"})

        await runner._consume_message(message=_cloud_event_message(), queue_name="events.jitsi")  # noqa: SLF001

        assert _sample("messages_processed_total", labels) == before + 1
        assert _sample("message_processing_seconds_count", {"queue": "events.jitsi"}) == duration_before + 1

    @pytest.mark.anyio
    async def test_exhausted_retries_count_as_retried(self) -> None:
        runner = _runner(FakeEventStore(failures=[_transient_error()] * 3), attempts=3)
        labels = {"queue": "events.jitsi", "event_type": "booking.created", "outcome": "retried"}
        before = _sample("messages_processed_total", labels)

        with pytest.raises(NackMessage):
            await runner._consume_message(message=_cloud_event_message(), queue_name="events.jitsi")  # noqa: SLF001

        assert _sample("messages_processed_total", labels) == before + 1

    @pytest.mark.anyio
    async def test_poison_save_counts_as_rejected(self) -> None:
        runner = _runner(FakeEventStore(failures=[ValueError("bad payload")]))
        labels = {"queue": "events.jitsi", "event_type": "booking.created", "outcome": "rejected"}
        before = _sample("messages_processed_total", labels)

        with pytest.raises(RejectMessage):
            await runner._consume_message(message=_cloud_event_message(), queue_name="events.jitsi")  # noqa: SLF001

        assert _sample("messages_processed_total", labels) == before + 1

    @pytest.mark.anyio
    async def test_unparseable_message_counts_as_rejected_unknown(self) -> None:
        runner = _runner(FakeEventStore())
        labels = {"queue": "events.jitsi", "event_type": "unknown", "outcome": "rejected"}
        before = _sample("messages_processed_total", labels)

        with pytest.raises(RejectMessage):
            await runner._consume_message(  # noqa: SLF001
                message=FakeMessage(headers={}, body=b"not-a-cloudevent"),
                queue_name="events.jitsi",
            )

        assert _sample("messages_processed_total", labels) == before + 1


class TestSaverBusinessCounters:
    @pytest.mark.anyio
    async def test_saved_event_increments_events_total(self) -> None:
        before = _sample("saver_events_total", {"event_type": "booking.created"})

        await _use_case(FakeEventRepository(), FakeBookingRepository(), FakeProjectionExecutor()).execute(
            **_execute_kwargs(),
        )

        assert _sample("saver_events_total", {"event_type": "booking.created"}) == before + 1

    @pytest.mark.anyio
    async def test_duplicate_event_is_not_counted(self) -> None:
        before = _sample("saver_events_total", {"event_type": "booking.created"})

        await _use_case(
            FakeEventRepository(inserted=False),
            FakeBookingRepository(),
            FakeProjectionExecutor(),
        ).execute(**_execute_kwargs())

        assert _sample("saver_events_total", {"event_type": "booking.created"}) == before

    @pytest.mark.anyio
    async def test_lifecycle_projection_counts_action(self, sample_parsed_event) -> None:
        before = _sample("saver_booking_lifecycle_total", {"action": "created"})

        result = await LifecycleProjection().handle(
            event=sample_parsed_event,
            booking_ref_id=1,
            organizer_user_id=None,
            client_user_id=None,
            queue_name="events.booking.lifecycle.saver",
        )

        assert result is not None
        assert _sample("saver_booking_lifecycle_total", {"action": "created"}) == before + 1
