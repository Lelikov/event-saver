"""DI container with clean architecture."""

from collections.abc import AsyncGenerator

import httpx
import structlog
from dishka import Provider, Scope, provide
from faststream.rabbit import Channel, ExchangeType, RabbitBroker, RabbitExchange, fastapi
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from event_saver.adapters import (
    BookingTimelineClassifier,
    RabbitEventConsumerRunner,
    SqlExecutor,
    UserIdBackfillRunner,
    UsersHttpResolver,
)
from event_saver.application.services.user_id_backfill import UserIdBackfillService
from event_saver.config import Settings
from event_saver.domain.services import BookingDataExtractor, EventParser, ParticipantExtractor
from event_saver.infrastructure.persistence.event_store_facade import CleanArchitectureEventStore
from event_saver.infrastructure.persistence.projections import (
    ChatEventProjection,
    ChatReadUpdateProjection,
    EmailNotificationProjection,
    EmailStatusHistoryProjection,
    LifecycleProjection,
    MeetingLinkProjection,
    TelegramNotificationProjection,
    VideoEventProjection,
)
from event_saver.infrastructure.persistence.repositories import (
    BookingRepository,
    EventRepository,
)
from event_saver.interfaces.backfill import IUserIdBackfillRunner
from event_saver.interfaces.consumer import IEventConsumerRunner
from event_saver.interfaces.event_store import IEventStore
from event_saver.interfaces.projection import IBookingEventClassifier
from event_saver.interfaces.projection_handler import IProjectionHandler
from event_saver.interfaces.sql import ISqlExecutor, ISqlExecutorFactory
from event_saver.interfaces.user_resolver import IUserResolver


from event_saver.telemetry import rabbit_telemetry_middlewares


logger = structlog.get_logger(__name__)


def build_rabbit_router(settings: Settings) -> fastapi.RabbitRouter:
    """Build the RabbitRouter with bounded prefetch (QoS) and graceful shutdown.

    Without prefetch_count RabbitMQ delivers the whole backlog at once,
    exhausting the DB pool and defeating x-max-priority ordering.
    """
    return fastapi.RabbitRouter(
        str(settings.rabbit_url),
        default_channel=Channel(prefetch_count=settings.rabbit_prefetch_count),
        graceful_timeout=settings.rabbit_graceful_timeout,
        middlewares=[*rabbit_telemetry_middlewares()],
    )


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
        )
        return settings

    # ========== Messaging Infrastructure ==========

    @provide(scope=Scope.APP)
    def provide_faststream_router(self, settings: Settings) -> fastapi.RabbitRouter:
        logger.info(
            "Creating FastStream RabbitRouter",
            rabbit_url=settings.rabbit_url,
            prefetch_count=settings.rabbit_prefetch_count,
            graceful_timeout=settings.rabbit_graceful_timeout,
        )
        return build_rabbit_router(settings)

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
        """Provide factory for creating SQL executors."""

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
    def provide_booking_repository(self, sql: ISqlExecutor) -> BookingRepository:
        return BookingRepository(sql)

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
    ) -> ChatEventProjection:
        return ChatEventProjection(classifier=classifier)

    @provide(scope=Scope.APP)
    def provide_chat_read_update_projection(self) -> ChatReadUpdateProjection:
        return ChatReadUpdateProjection()

    @provide(scope=Scope.APP)
    def provide_video_event_projection(self, classifier: IBookingEventClassifier) -> VideoEventProjection:
        return VideoEventProjection(classifier=classifier)

    @provide(scope=Scope.APP)
    def provide_lifecycle_projection(self) -> LifecycleProjection:
        return LifecycleProjection()

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
        lifecycle: LifecycleProjection,
    ) -> list[IProjectionHandler]:
        """Collect all projection handlers into a list."""
        return [
            meeting_link,
            email_notification,
            telegram_notification,
            email_status_history,
            chat_event,
            chat_read_update,
            video_event,
            lifecycle,
        ]

    # ========== Event Store (Facade) ==========

    @provide(scope=Scope.APP)
    def provide_event_store(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        event_parser: EventParser,
        participant_extractor: ParticipantExtractor,
        booking_data_extractor: BookingDataExtractor,
        projection_handlers: list[IProjectionHandler],
        sql_executor_factory: ISqlExecutorFactory,
    ) -> IEventStore:
        """Provide event store that uses clean architecture.

        This facade creates use case for each save_event call.
        """
        return CleanArchitectureEventStore(
            sessionmaker=sessionmaker,
            event_parser=event_parser,
            participant_extractor=participant_extractor,
            booking_data_extractor=booking_data_extractor,
            projection_handlers=projection_handlers,
            sql_executor_factory=sql_executor_factory,
        )

    # ========== Consumer ==========

    @provide(scope=Scope.APP)
    def provide_event_consumer_runner(
        self,
        broker: RabbitBroker,
        exchange: RabbitExchange,
        event_store: IEventStore,
    ) -> IEventConsumerRunner:
        return RabbitEventConsumerRunner(
            broker=broker,
            exchange=exchange,
            event_store=event_store,
        )

    # ========== user_id backfill (audit-v2 follow-up #9) ==========

    @provide(scope=Scope.APP)
    async def provide_event_users_http_client(self, settings: Settings) -> AsyncGenerator[httpx.AsyncClient]:
        if settings.user_id_backfill_enabled and not settings.event_users_api_url:
            msg = "USER_ID_BACKFILL_ENABLED=True requires EVENT_USERS_API_URL"
            raise ValueError(msg)
        client = httpx.AsyncClient(base_url=settings.event_users_api_url, timeout=10.0)
        try:
            yield client
        finally:
            await client.aclose()

    @provide(scope=Scope.APP)
    def provide_user_resolver(self, settings: Settings, http_client: httpx.AsyncClient) -> IUserResolver:
        return UsersHttpResolver(http_client=http_client, api_token=settings.event_users_api_token)

    @provide(scope=Scope.APP)
    def provide_user_id_backfill_service(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        sql_executor_factory: ISqlExecutorFactory,
        resolver: IUserResolver,
    ) -> UserIdBackfillService:
        return UserIdBackfillService(
            sessionmaker=sessionmaker,
            sql_executor_factory=sql_executor_factory,
            resolver=resolver,
            batch_size=settings.user_id_backfill_batch_size,
        )

    @provide(scope=Scope.APP)
    def provide_user_id_backfill_runner(
        self,
        settings: Settings,
        service: UserIdBackfillService,
    ) -> IUserIdBackfillRunner:
        return UserIdBackfillRunner(
            service=service,
            interval_seconds=settings.user_id_backfill_interval_seconds,
            enabled=settings.user_id_backfill_enabled,
        )
