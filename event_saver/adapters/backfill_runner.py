"""Asyncio background loop driving the periodic user_id backfill."""

from __future__ import annotations
import asyncio
import contextlib
from typing import TYPE_CHECKING

import structlog

from event_saver.interfaces.backfill import IUserIdBackfillRunner


if TYPE_CHECKING:
    from event_saver.application.services.user_id_backfill import UserIdBackfillService

logger = structlog.get_logger(__name__)


class UserIdBackfillRunner(IUserIdBackfillRunner):
    """Owns the asyncio task; started/stopped from the app lifespan."""

    def __init__(
        self,
        *,
        service: UserIdBackfillService,
        interval_seconds: float,
        enabled: bool,
    ) -> None:
        self._service = service
        self._interval_seconds = interval_seconds
        self._enabled = enabled
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not self._enabled:
            logger.info("user_id backfill disabled (USER_ID_BACKFILL_ENABLED=False)")
            return
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="user-id-backfill")
        logger.info("user_id backfill started", interval_seconds=self._interval_seconds)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("user_id backfill stopped")

    async def _loop(self) -> None:
        while True:
            await self._run_cycle()
            await asyncio.sleep(self._interval_seconds)

    async def _run_cycle(self) -> None:
        try:
            summary = await self._service.run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            # The loop must survive unexpected failures (DB restarts etc.);
            # the next interval retries from scratch.
            logger.exception("user_id backfill cycle failed")
            return
        logger.info(
            "user_id backfill cycle complete",
            scanned_bookings=summary.scanned_bookings,
            resolved=summary.resolved,
            unresolved=summary.unresolved,
            missing_email=summary.missing_email,
            aborted=summary.aborted,
        )
