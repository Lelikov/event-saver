from pydantic import AmqpDsn, Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    debug: bool = False
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid_levels:
            raise ValueError(
                f"Invalid log_level: {v!r}. Must be one of {sorted(valid_levels)}",
            )
        return upper

    # Queues/bindings/arguments come from event_schemas.queues.SAVER_QUEUES (single source of truth)
    rabbit_url: AmqpDsn = "amqp://guest:guest@localhost:5672/"
    rabbit_exchange: str = "events"
    # Bounded prefetch keeps backlog floods from exhausting the DB pool (pool_size=10, max_overflow=20)
    # and preserves x-max-priority ordering on the queues.
    rabbit_prefetch_count: int = 10
    # Seconds FastStream waits for in-flight handlers before force-cancelling on shutdown.
    rabbit_graceful_timeout: float = 30.0

    postgres_dsn: PostgresDsn = Field(strict=True)

    # --- user_id backfill / reconciliation (audit-v2 follow-up #9) ---
    # When event-users is down at ingress, event-receiver publishes participants
    # with user_id=None; this periodic task re-resolves them via event-users.
    user_id_backfill_enabled: bool = False
    user_id_backfill_interval_seconds: float = 300.0
    user_id_backfill_batch_size: int = 100
    # Required when user_id_backfill_enabled=True (validated at DI wiring).
    event_users_api_url: str = ""
    event_users_api_token: str = ""
