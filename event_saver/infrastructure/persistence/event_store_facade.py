"""Facade for event store that uses clean architecture use case."""

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_saver.application.services.projection_executor import ProjectionExecutor
from event_saver.application.use_cases.ingest_event import IngestEventUseCase
from event_saver.domain.services import BookingDataExtractor, EventParser, ParticipantExtractor
from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.infrastructure.persistence.repositories import (
    BookingRepository,
    EventRepository,
    ParticipantRepository,
)
from event_saver.interfaces.event_store import IEventStore
from event_saver.interfaces.sql import ISqlExecutorFactory


class CleanArchitectureEventStore(IEventStore):
    """Event store facade that delegates to clean architecture use case.

    Adapts the use case to the IEventStore interface for compatibility.
    Each save_event call creates a new session and use case instance.
    """

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        event_parser: EventParser,
        participant_extractor: ParticipantExtractor,
        booking_data_extractor: BookingDataExtractor,
        projection_handlers: list[BaseProjection],
        sql_executor_factory: ISqlExecutorFactory,
        getstream_user_id_decoder: callable,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_parser = event_parser
        self._participant_extractor = participant_extractor
        self._booking_data_extractor = booking_data_extractor
        self._projection_handlers = projection_handlers
        self._sql_executor_factory = sql_executor_factory
        self._getstream_user_id_decoder = getstream_user_id_decoder

    async def save_event(
        self,
        *,
        queue_name: str,
        event_id: str,
        booking_id: str | None,
        event_type: str,
        source: str,
        occurred_at: datetime,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        dataschema: str | None = None,
    ) -> None:
        """Save event by delegating to use case.

        Creates a new session and use case for each call.
        """
        async with self._sessionmaker() as session:
            # Create request-scoped dependencies
            sql = self._sql_executor_factory(session)

            event_repository = EventRepository(sql)
            participant_repository = ParticipantRepository(sql)
            booking_repository = BookingRepository(sql)

            projection_executor = ProjectionExecutor(
                sql=sql,
                handlers=self._projection_handlers,
            )

            use_case = IngestEventUseCase(
                event_parser=self._event_parser,
                participant_extractor=self._participant_extractor,
                booking_data_extractor=self._booking_data_extractor,
                event_repository=event_repository,
                participant_repository=participant_repository,
                booking_repository=booking_repository,
                projection_executor=projection_executor,
                getstream_user_id_decoder=self._getstream_user_id_decoder,
            )

            # Execute use case
            await use_case.execute(
                queue_name=queue_name,
                event_id=event_id,
                event_type=event_type,
                source=source,
                time=occurred_at,
                booking_id=booking_id,
                data=payload,
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                span_id=span_id,
                dataschema=dataschema,
            )

            # Commit transaction
            await session.commit()
