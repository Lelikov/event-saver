"""Service for executing projection handlers."""

import structlog

from event_saver.domain.models.event import ParsedEvent
from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.interfaces.sql import ISqlExecutor


logger = structlog.get_logger(__name__)


class ProjectionExecutor:
    """Executes projection handlers and persists results.

    Separates projection logic from SQL execution infrastructure.
    """

    def __init__(
        self,
        *,
        sql: ISqlExecutor,
        handlers: list[BaseProjection],
    ) -> None:
        self._sql = sql
        self._handlers = handlers

    async def execute_projections(
        self,
        *,
        event: ParsedEvent,
        queue_name: str,
        booking_ref_id: int,
        organizer_id: int | None,
        client_id: int | None,
    ) -> None:
        """Execute all applicable projection handlers for the event.

        Continues processing even if individual projections fail.
        """
        for handler in self._handlers:
            if not handler.can_handle(event):
                continue

            try:
                result = await handler.handle(
                    event=event,
                    booking_ref_id=booking_ref_id,
                    organizer_ref_id=organizer_id,
                    client_ref_id=client_id,
                    queue_name=queue_name,
                )

                if result is not None:
                    sql, params = result
                    await self._sql.execute(sql, params)

                    logger.debug(
                        "Projection executed",
                        handler=handler.__class__.__name__,
                        event_type=event.event_type,
                    )

            except Exception:
                logger.exception(
                    "Projection failed",
                    handler=handler.__class__.__name__,
                    event_id=event.event_id,
                    event_type=event.event_type,
                )
                # Continue with other projections
