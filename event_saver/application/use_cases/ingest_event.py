"""Use case for ingesting events - orchestrates the entire event processing flow."""

import uuid
from typing import Any

import structlog
from event_schemas.types import EventType

from event_saver import metrics
from event_saver.application.services.projection_executor import ProjectionExecutor
from event_saver.domain.services import BookingDataExtractor, EventParser, ParticipantExtractor
from event_saver.interfaces.repositories import IBookingRepository, IEventRepository


logger = structlog.get_logger(__name__)


class IngestEventUseCase:
    """Main use case for event ingestion."""

    def __init__(
        self,
        *,
        event_parser: EventParser,
        participant_extractor: ParticipantExtractor,
        booking_data_extractor: BookingDataExtractor,
        event_repository: IEventRepository,
        booking_repository: IBookingRepository,
        projection_executor: ProjectionExecutor,
    ) -> None:
        self._event_parser = event_parser
        self._participant_extractor = participant_extractor
        self._booking_data_extractor = booking_data_extractor
        self._event_repository = event_repository
        self._booking_repository = booking_repository
        self._projection_executor = projection_executor

    async def execute(
        self,
        *,
        queue_name: str,
        event_id: str,
        event_type: str,
        source: str,
        time: Any,
        booking_id: str | None,
        data: dict[str, Any] | None,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        dataschema: str | None = None,
    ) -> None:
        """Execute event ingestion flow."""
        event = self._event_parser.parse(
            event_id=event_id,
            event_type=event_type,
            source=source,
            time=time,
            booking_id=booking_id,
            data=data,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            span_id=span_id,
            dataschema=dataschema,
        )

        is_inserted = await self._event_repository.save(event)
        if not is_inserted:
            logger.info(
                "Event skipped (duplicate)",
                event_id=event.event_id,
                event_type=event.event_type,
                booking_id=event.booking_id,
            )
            return

        metrics.EVENTS_TOTAL.labels(event_type=str(event.event_type)).inc()
        logger.info(
            "Raw event saved",
            event_id=event.event_id,
            event_type=event.event_type,
            booking_id=event.booking_id,
        )

        if not event.booking_id:
            return

        organizer_user_id, client_user_id = self._process_participants(event)

        booking_ref_id = await self._booking_repository.get_or_none(
            booking_id=event.booking_id,
            queue_name=queue_name,
        )

        if booking_ref_id is None:
            booking_data = self._booking_data_extractor.extract(
                booking_id=event.booking_id,
                event_type=event.event_type,
                payload=event.payload,
            )

            booking_ref_id = await self._booking_repository.upsert(
                booking_data=booking_data,
                occurred_at=event.occurred_at,
                organizer_user_id=organizer_user_id,
                client_user_id=client_user_id,
            )

            if event.event_type in (EventType.BOOKING_CREATED, EventType.BOOKING_REASSIGNED) and organizer_user_id:
                await self._booking_repository.save_organizer_history(
                    booking_id=booking_ref_id,
                    organizer_user_id=organizer_user_id,
                    source_event_id=event.event_id,
                    occurred_at=event.occurred_at,
                )

            if event.event_type == EventType.BOOKING_CLIENT_REASSIGNED:
                new_client_id_str = event.payload.get("original", {}).get("new_client_user_id")
                if new_client_id_str:
                    try:
                        new_client_uuid = uuid.UUID(new_client_id_str)
                    except ValueError, AttributeError:
                        new_client_uuid = None
                    if new_client_uuid:
                        await self._booking_repository.update_client(
                            booking_ref_id=booking_ref_id,
                            client_user_id=new_client_uuid,
                        )
                        client_user_id = new_client_uuid

            logger.info(
                "Booking upserted",
                booking_ref_id=booking_ref_id,
                booking_uid=event.booking_id,
            )

        await self._projection_executor.execute_projections(
            event=event,
            queue_name=queue_name,
            booking_ref_id=booking_ref_id,
            organizer_user_id=organizer_user_id,
            client_user_id=client_user_id,
        )

    def _process_participants(self, event: Any) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        """Extract organizer and client UUIDs from event payload."""
        return self._participant_extractor.extract(event.payload)
