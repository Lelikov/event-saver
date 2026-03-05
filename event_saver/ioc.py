from collections.abc import AsyncGenerator

import structlog
from dishka import Provider, Scope, provide
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, fastapi
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from event_saver.adapters import (
    CloudEventPublisher,
    RabbitEventConsumerRunner,
    RabbitTopologyManager,
    SqlEventStore,
    SqlExecutor,
)
from event_saver.config import Settings
from event_saver.interfaces.consumer import IEventConsumerRunner
from event_saver.interfaces.event_store import IEventStore
from event_saver.interfaces.publisher import ICloudEventPublisher, ITopologyManager
from event_saver.interfaces.routing import IEventRouter
from event_saver.interfaces.sql import ISqlExecutor
from event_saver.routing import EventRouter


logger = structlog.get_logger(__name__)


class AppProvider(Provider):
    @provide(scope=Scope.APP)
    def provide_settings(self) -> Settings:
        settings = Settings()
        logger.info(
            "Settings initialized",
            debug=settings.debug,
            log_level=settings.log_level,
            rabbit_exchange=settings.rabbit_exchange,
            routing_rules_count=len(settings.event_routing_rules),
        )
        return settings

    @provide(scope=Scope.APP)
    def provide_faststream_router(self, settings: Settings) -> fastapi.RabbitRouter:
        logger.info("Creating FastStream RabbitRouter", rabbit_url=settings.rabbit_url)
        return fastapi.RabbitRouter(str(settings.rabbit_url))

    @provide(scope=Scope.APP)
    def provide_broker(self, router: fastapi.RabbitRouter) -> RabbitBroker:
        logger.info("Providing RabbitBroker from FastStream router")
        return router.broker

    @provide(scope=Scope.APP)
    def provide_exchange(self, settings: Settings) -> RabbitExchange:
        logger.info("Creating RabbitExchange", exchange=settings.rabbit_exchange)
        return RabbitExchange(
            name=settings.rabbit_exchange,
            type=ExchangeType.TOPIC,
            durable=True,
        )

    @provide(scope=Scope.APP)
    def provide_event_router(self, settings: Settings) -> IEventRouter:
        logger.info("Providing EventRouter")
        return EventRouter(settings.routing)

    @provide(scope=Scope.APP)
    def provide_publisher(
        self,
        broker: RabbitBroker,
        exchange: RabbitExchange,
        event_router: IEventRouter,
    ) -> ICloudEventPublisher:
        logger.info("Providing CloudEventPublisher")
        return CloudEventPublisher(
            broker=broker,
            exchange=exchange,
            router_by_event=event_router,
        )

    @provide(scope=Scope.APP)
    def provide_topology_manager(
        self,
        settings: Settings,
        broker: RabbitBroker,
        exchange: RabbitExchange,
    ) -> ITopologyManager:
        logger.info(
            "Providing RabbitTopologyManager",
            topology_queue_count=len(settings.topology_queues),
        )
        return RabbitTopologyManager(
            broker=broker,
            exchange=exchange,
            topology_queues=settings.topology_queues,
        )

    @provide(scope=Scope.APP)
    async def provide_db_engine(
        self,
        settings: Settings,
    ) -> AsyncGenerator[AsyncEngine, None]:
        engine = create_async_engine(
            str(settings.postgres_dsn),
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
        try:
            yield engine
        finally:
            await engine.dispose()

    @provide(scope=Scope.APP)
    def provide_sessionmaker(
        self,
        engine: AsyncEngine,
    ) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @provide(scope=Scope.REQUEST)
    async def provide_session(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            yield session

    @provide(scope=Scope.REQUEST)
    def provide_sql_executor(self, session: AsyncSession) -> ISqlExecutor:
        return SqlExecutor(session)

    @provide(scope=Scope.APP)
    def provide_event_store(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> IEventStore:
        return SqlEventStore(sessionmaker)

    @provide(scope=Scope.APP)
    def provide_event_consumer_runner(
        self,
        settings: Settings,
        broker: RabbitBroker,
        exchange: RabbitExchange,
        event_store: IEventStore,
    ) -> IEventConsumerRunner:
        return RabbitEventConsumerRunner(
            broker=broker,
            exchange=exchange,
            queue_names=settings.topology_queues,
            event_store=event_store,
        )
