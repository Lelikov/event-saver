import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from logging import getLevelNamesMapping

import httpx
import structlog
from dishka import make_async_container
from dishka.integrations.fastapi import FastapiProvider, FromDishka, setup_dishka
from fastapi import FastAPI, HTTPException

from event_saver.config import Settings
from event_saver.interfaces.consumer import IEventConsumerRunner
from event_saver.interfaces.users import IUsersClient
from event_saver.ioc import AppProvider
from event_saver.logger import setup_logger


container = make_async_container(AppProvider(), FastapiProvider())

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    settings = await container.get(Settings)
    log_level = getLevelNamesMapping().get(settings.log_level, logging.INFO)
    setup_logger(log_level=log_level, console_render=settings.debug)

    logger.info(
        "Starting event receiver application",
        log_level=settings.log_level,
        debug=settings.debug,
        rabbit_exchange=settings.rabbit_exchange,
    )

    consumer_runner = await container.get(IEventConsumerRunner)
    await consumer_runner.start()
    logger.info("Event consumer started and application is ready")

    yield

    logger.info("Shutting down event receiver application")
    await consumer_runner.stop()
    await container.close()
    logger.info("Event receiver application shutdown complete")


app = FastAPI(title="event-saver", version="0.1.0", lifespan=lifespan)
setup_dishka(container=container, app=app)


@app.get("/api/users/{user_id}")
async def proxy_get_user(
    user_id: uuid.UUID,
    client: FromDishka[IUsersClient],
) -> dict:
    try:
        return await client.get_user(user_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code) from exc
