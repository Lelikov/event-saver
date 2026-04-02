"""DI container with clean architecture."""

import hashlib
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
    BookingTimelineClassifier,
    CloudEventPublisher,
    RabbitEventConsumerRunner,
    RabbitTopologyManager,
    SqlExecutor,
)
from event_saver.config import Settings
from event_saver.domain.services import BookingDataExtractor, EventParser, ParticipantExtractor
from event_saver.infrastructure.persistence.event_store_facade import CleanArchitectureEventStore
from event_saver.infrastructure.persistence.projections import (
    ChatEventProjection,
    ChatReadUpdateProjection,
    EmailNotificationProjection,
    EmailStatusHistoryProjection,
    MeetingLinkProjection,
    TelegramNotificationProjection,
    VideoEventProjection,
)
from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.infrastructure.persistence.repositories import (
    BookingRepository,
    EventRepository,
    ParticipantRepository,
)
from event_saver.interfaces.consumer import IEventConsumerRunner
from event_saver.interfaces.event_store import IEventStore
from event_saver.interfaces.projection import IBookingEventClassifier
from event_saver.interfaces.publisher import ICloudEventPublisher, ITopologyManager
from event_saver.interfaces.routing import IEventRouter
from event_saver.interfaces.sql import ISqlExecutor, ISqlExecutorFactory
from event_saver.routing import EventRouter
from event_saver.utils import decode_user_id


logger = structlog.get_logger(__name__)


class AppProvider(Provider):
    """DI provider with clean architecture."""

    # ========== Configuration ==========

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

    # ========== Messaging Infrastructure ==========

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

    # ========== Database Infrastructure ==========

    @provide(scope=Scope.APP)
    async def provide_db_engine(
        self,
        settings: Settings,
    ) -> AsyncGenerator[AsyncEngine]:
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
    ) -> AsyncGenerator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    @provide(scope=Scope.REQUEST)
    def provide_sql_executor(self, session: AsyncSession) -> ISqlExecutor:
        return SqlExecutor(session)

    @provide(scope=Scope.APP)
    def provide_sql_executor_factory(self) -> ISqlExecutorFactory:
        """Factory for creating SQL executors."""

        def factory(session: AsyncSession) -> ISqlExecutor:
            return SqlExecutor(session)

        return factory

    # ========== Domain Services ==========

    @provide(scope=Scope.APP)
    def provide_event_parser(self) -> EventParser:
        return EventParser()

    @provide(scope=Scope.APP)
    def provide_participant_extractor(self) -> ParticipantExtractor:
        return ParticipantExtractor()

    @provide(scope=Scope.APP)
    def provide_booking_data_extractor(self) -> BookingDataExtractor:
        return BookingDataExtractor()

    @provide(scope=Scope.APP)
    def provide_booking_event_classifier(self) -> IBookingEventClassifier:
        return BookingTimelineClassifier()

    # ========== Repositories ==========

    @provide(scope=Scope.REQUEST)
    def provide_event_repository(self, sql: ISqlExecutor) -> EventRepository:
        return EventRepository(sql)

    @provide(scope=Scope.REQUEST)
    def provide_participant_repository(self, sql: ISqlExecutor) -> ParticipantRepository:
        return ParticipantRepository(sql)

    @provide(scope=Scope.REQUEST)
    def provide_booking_repository(self, sql: ISqlExecutor) -> BookingRepository:
        return BookingRepository(sql)

    # ========== User ID Decoder ==========

    @provide(scope=Scope.APP)
    def provide_getstream_user_id_decoder(self, settings: Settings) -> callable:
        """Provides a callable that decodes GetStream user IDs."""

        def decoder(encoded_user_id: str) -> str:
            if not settings.getstream_user_id_encryption_key:
                return encoded_user_id

            try:
                key = hashlib.sha256(settings.getstream_user_id_encryption_key.encode()).digest()
                return decode_user_id(encoded_user_id=encoded_user_id, encryption_key=key)
            except Exception:
                return encoded_user_id

        return decoder

    # ========== Projection Handlers ==========

    @provide(scope=Scope.APP)
    def provide_meeting_link_projection(self) -> MeetingLinkProjection:
        return MeetingLinkProjection()

    @provide(scope=Scope.APP)
    def provide_email_notification_projection(self) -> EmailNotificationProjection:
        return EmailNotificationProjection()

    @provide(scope=Scope.APP)
    def provide_telegram_notification_projection(self) -> TelegramNotificationProjection:
        return TelegramNotificationProjection()

    @provide(scope=Scope.APP)
    def provide_email_status_history_projection(self) -> EmailStatusHistoryProjection:
        return EmailStatusHistoryProjection()

    @provide(scope=Scope.APP)
    def provide_chat_event_projection(
        self,
        classifier: IBookingEventClassifier,
        decoder: callable,
    ) -> ChatEventProjection:
        return ChatEventProjection(
            classifier=classifier,
            decode_user_id=decoder,
        )

    @provide(scope=Scope.APP)
    def provide_chat_read_update_projection(self, decoder: callable) -> ChatReadUpdateProjection:
        return ChatReadUpdateProjection(decode_user_id=decoder)

    @provide(scope=Scope.APP)
    def provide_video_event_projection(self, classifier: IBookingEventClassifier) -> VideoEventProjection:
        return VideoEventProjection(classifier=classifier)

    @provide(scope=Scope.APP)
    def provide_projection_handlers(
        self,
        meeting_link: MeetingLinkProjection,
        email_notification: EmailNotificationProjection,
        telegram_notification: TelegramNotificationProjection,
        email_status_history: EmailStatusHistoryProjection,
        chat_event: ChatEventProjection,
        chat_read_update: ChatReadUpdateProjection,
        video_event: VideoEventProjection,
    ) -> list[BaseProjection]:
        """Collect all projection handlers into a list."""
        return [
            meeting_link,
            email_notification,
            telegram_notification,
            email_status_history,
            chat_event,
            chat_read_update,
            video_event,
        ]

    # ========== Event Store (Facade) ==========

    @provide(scope=Scope.APP)
    def provide_event_store(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        event_parser: EventParser,
        participant_extractor: ParticipantExtractor,
        booking_data_extractor: BookingDataExtractor,
        projection_handlers: list[BaseProjection],
        sql_executor_factory: ISqlExecutorFactory,
        decoder: callable,
    ) -> IEventStore:
        """Provides event store that uses clean architecture.

        This facade creates use case for each save_event call.
        """
        return CleanArchitectureEventStore(
            sessionmaker=sessionmaker,
            event_parser=event_parser,
            participant_extractor=participant_extractor,
            booking_data_extractor=booking_data_extractor,
            projection_handlers=projection_handlers,
            sql_executor_factory=sql_executor_factory,
            getstream_user_id_decoder=decoder,
        )

    # ========== Consumer ==========

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
