"""Facade for event store that uses clean architecture use case."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_saver.application.services.projection_executor import ProjectionExecutor
from event_saver.application.use_cases.ingest_event import IngestEventUseCase
from event_saver.domain.services import BookingDataExtractor, EventParser, ParticipantExtractor
from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.infrastructure.persistence.repositories import BookingRepository, EventRepository
from event_saver.interfaces.event_store import IEventStore
from event_saver.interfaces.sql import ISqlExecutorFactory


class CleanArchitectureEventStore(IEventStore):
    """Event store facade that delegates to clean architecture use case."""

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        event_parser: EventParser,
        participant_extractor: ParticipantExtractor,
        booking_data_extractor: BookingDataExtractor,
        projection_handlers: list[BaseProjection],
        sql_executor_factory: ISqlExecutorFactory,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_parser = event_parser
        self._participant_extractor = participant_extractor
        self._booking_data_extractor = booking_data_extractor
        self._projection_handlers = projection_handlers
        self._sql_executor_factory = sql_executor_factory

    async def save_event(
        self,
        *,
        queue_name: str,
        event_id: str,
        booking_id: str | None,
        event_type: str,
        source: str,
        time: Any,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        dataschema: str | None = None,
    ) -> None:
        """Save event by delegating to use case."""
        async with self._sessionmaker() as session:
            sql = self._sql_executor_factory(session)

            event_repository = EventRepository(sql)
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
                booking_repository=booking_repository,
                projection_executor=projection_executor,
            )

            await use_case.execute(
                queue_name=queue_name,
                event_id=event_id,
                event_type=event_type,
                source=source,
                time=time,
                booking_id=booking_id,
                data=payload,
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                span_id=span_id,
                dataschema=dataschema,
            )

            await session.commit()
