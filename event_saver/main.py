import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from logging import getLevelNamesMapping

import structlog
from dishka import make_async_container
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from event_saver.config import Settings
from event_saver.interfaces.consumer import IEventConsumerRunner
from event_saver.ioc import AppProvider
from event_saver.logger import setup_logger


container = make_async_container(AppProvider(), FastapiProvider())

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    settings = await container.get(Settings)
    log_level = getLevelNamesMapping().get(settings.log_level, logging.INFO)
    setup_logger(log_level=log_level, console_render=False)

    logger.info(
        "Starting event-saver application",
        log_level=settings.log_level,
        debug=settings.debug,
        rabbit_exchange=settings.rabbit_exchange,
    )

    consumer_runner = await container.get(IEventConsumerRunner)
    await consumer_runner.start()
    logger.info("Event consumer started and application is ready")

    yield

    logger.info("Shutting down event-saver application")
    await consumer_runner.stop()
    await container.close()
    logger.info("event-saver application shutdown complete")


app = FastAPI(title="event-saver", version="0.1.0", lifespan=lifespan)
setup_dishka(container=container, app=app)


async def _check_database() -> bool:
    """Verify PostgreSQL connectivity with a SELECT 1."""
    try:
        engine = await container.get(AsyncEngine)
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except Exception:
        logger.exception("Readiness check failed: database unreachable")
        return False
    return True


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: the process is up and serving HTTP."""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> JSONResponse:
    """Readiness probe: verifies database connectivity."""
    if not await _check_database():
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ready"})
