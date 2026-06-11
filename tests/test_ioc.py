"""Tests for broker construction: prefetch (QoS) and graceful shutdown settings."""

from event_saver.config import Settings
from event_saver.ioc import build_rabbit_router


def _settings(**overrides) -> Settings:
    return Settings(postgres_dsn="postgresql+asyncpg://u:p@localhost:5432/db", _env_file=None, **overrides)


class TestBuildRabbitRouter:
    def test_default_channel_has_bounded_prefetch(self) -> None:
        router = build_rabbit_router(_settings(rabbit_prefetch_count=25))

        channel_manager = router.broker.config.broker_config.channel_manager
        default_channel = channel_manager._ChannelManagerImpl__default_channel  # noqa: SLF001
        assert default_channel.prefetch_count == 25

    def test_graceful_timeout_is_set(self) -> None:
        router = build_rabbit_router(_settings(rabbit_graceful_timeout=42.0))

        assert router.broker.config.graceful_timeout == 42.0

    def test_settings_defaults_are_sane(self) -> None:
        settings = _settings()

        # prefetch must not exceed the DB pool headroom (pool_size=10, max_overflow=20)
        assert 0 < settings.rabbit_prefetch_count <= 30
        assert settings.rabbit_graceful_timeout > 0
