"""Use case for ingesting events - orchestrates the entire event processing flow."""

from typing import Any

import structlog

from event_saver.application.services.projection_executor import ProjectionExecutor
from event_saver.domain.models.participant import Participant
from event_saver.domain.services import BookingDataExtractor, EventParser, ParticipantExtractor
from event_saver.event_types import EventType, SourceType
from event_saver.infrastructure.persistence.repositories import (
    BookingRepository,
    EventRepository,
    ParticipantRepository,
)


logger = structlog.get_logger(__name__)


class IngestEventUseCase:
    """Main use case for event ingestion.

    Orchestrates:
    1. Event parsing (domain service)
    2. Raw event persistence (repository)
    3. Participant extraction and persistence (domain service + repository)
    4. Booking data extraction and persistence (domain service + repository)
    5. Projection building (projection executor)

    Single Responsibility: Orchestration only, no business logic.
    """

    def __init__(
        self,
        *,
        event_parser: EventParser,
        participant_extractor: ParticipantExtractor,
        booking_data_extractor: BookingDataExtractor,
        event_repository: EventRepository,
        participant_repository: ParticipantRepository,
        booking_repository: BookingRepository,
        projection_executor: ProjectionExecutor,
        getstream_user_id_decoder: callable,
    ) -> None:
        self._event_parser = event_parser
        self._participant_extractor = participant_extractor
        self._booking_data_extractor = booking_data_extractor
        self._event_repository = event_repository
        self._participant_repository = participant_repository
        self._booking_repository = booking_repository
        self._projection_executor = projection_executor
        self._getstream_user_id_decoder = getstream_user_id_decoder

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
        """Execute event ingestion flow.

        Args:
            queue_name: RabbitMQ queue name (for routing)
            event_id: CloudEvent ID
            event_type: CloudEvent type
            source: CloudEvent source
            time: CloudEvent time
            booking_id: Optional booking identifier
            data: Event payload
            idempotency_key: Optional idempotency key for deduplication
            trace_id: Optional trace ID for distributed tracing
            span_id: Optional span ID for distributed tracing
            dataschema: Optional schema version

        """
        # Step 1: Parse event into domain model
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

        # Step 2: Save raw event (with deduplication)
        is_inserted = await self._event_repository.save(event)
        if not is_inserted:
            logger.info(
                "Event skipped (duplicate)",
                event_id=event.event_id,
                event_type=event.event_type,
                booking_id=event.booking_id,
            )
            return

        logger.info(
            "Raw event saved",
            event_id=event.event_id,
            event_type=event.event_type,
            booking_id=event.booking_id,
        )

        # Step 3: Early exit if no booking_id (can't build projections)
        if not event.booking_id:
            return

        # Step 4: Extract and persist participants
        organizer_id, client_id = await self._process_participants(event)

        # Step 5: Get or create booking
        booking_ref_id = await self._booking_repository.get_or_none(
            booking_id=event.booking_id,
            queue_name=queue_name,
        )

        if booking_ref_id is None:
            # Extract booking data and create/update booking
            booking_data = self._booking_data_extractor.extract(
                booking_id=event.booking_id,
                event_type=event.event_type,
                payload=event.payload,
            )

            booking_ref_id = await self._booking_repository.upsert(
                booking_data=booking_data,
                occurred_at=event.occurred_at,
                organizer_id=organizer_id,
                client_id=client_id,
            )

            # Save organizer history for relevant events
            if event.event_type in (EventType.BOOKING_CREATED, EventType.BOOKING_REASSIGNED) and organizer_id:
                await self._booking_repository.save_organizer_history(
                    booking_id=booking_ref_id,
                    organizer_id=organizer_id,
                    source_event_id=event.event_id,
                    occurred_at=event.occurred_at,
                )

            logger.info(
                "Booking upserted",
                booking_ref_id=booking_ref_id,
                booking_uid=event.booking_id,
            )

        # Step 6: Execute all applicable projections
        await self._projection_executor.execute_projections(
            event=event,
            queue_name=queue_name,
            booking_ref_id=booking_ref_id,
            organizer_id=organizer_id,
            client_id=client_id,
        )

    async def _process_participants(self, event) -> tuple[int | None, int | None]:
        """Extract and persist participants from event.

        Returns tuple of (organizer_id, client_id).
        """
        # Extract participants - no more if statements needed!
        # ParticipantExtractor handles normalized structure automatically
        participants = self._participant_extractor.extract(event.payload)

        organizer_id: int | None = None
        client_id: int | None = None

        for participant in participants:
            participant_id = await self._participant_repository.upsert_if_changed(participant)

            if participant.role == "organizer":
                organizer_id = participant_id
            elif participant.role == "client":
                client_id = participant_id

        return organizer_id, client_id
