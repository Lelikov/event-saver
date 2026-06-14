"""Service for executing projection handlers."""

import uuid

import structlog
from opentelemetry import trace

from event_saver.domain.models.event import ParsedEvent
from event_saver.interfaces.projection_handler import IProjectionHandler
from event_saver.interfaces.sql import ISqlExecutor


logger = structlog.get_logger(__name__)

_tracer = trace.get_tracer(__name__)


class ProjectionExecutor:
    """Executes projection handlers and persists results."""

    def __init__(
        self,
        *,
        sql: ISqlExecutor,
        handlers: list[IProjectionHandler],
    ) -> None:
        self._sql = sql
        self._handlers = handlers

    async def execute_projections(
        self,
        *,
        event: ParsedEvent,
        queue_name: str,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
    ) -> None:
        """Execute all applicable projection handlers for the event."""
        for handler in self._handlers:
            if not handler.can_handle(event):
                continue

            projection_name = handler.__class__.__name__
            try:
                with _tracer.start_as_current_span("saver.projection_execute") as span:
                    span.set_attribute("projection.name", projection_name)
                    result = await handler.handle(
                        event=event,
                        booking_ref_id=booking_ref_id,
                        organizer_user_id=organizer_user_id,
                        client_user_id=client_user_id,
                        queue_name=queue_name,
                    )

                    if result is not None:
                        sql, params = result
                        await self._sql.execute(sql, params)

                logger.debug(
                    "Projection executed",
                    handler=projection_name,
                    event_type=event.event_type,
                )

            except Exception:
                logger.exception(
                    "projection_failed",
                    projection_name=projection_name,
                    event_type=event.event_type,
                    booking_id=event.booking_id,
                    event_id=event.event_id,
                )
                raise
