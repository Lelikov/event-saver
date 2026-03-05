from pydantic import AmqpDsn, Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from event_saver.routing import RouteRule, RoutingConfig


def _default_route_rules() -> list[RouteRule]:
    return [
        RouteRule(
            destination="events.mail",
            source_pattern="unisender-go",
            type_pattern="unisender.*",
        ),
        RouteRule(
            destination="events.message",
            source_pattern="getstream",
            type_pattern="getstream.*",
        ),
    ]


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

    rabbit_url: AmqpDsn = "amqp://guest:guest@localhost:5672/"
    rabbit_exchange: str = "events"
    default_rabbit_destination: str = "events.unrouted"
    event_routing_rules: list[RouteRule] = Field(default_factory=_default_route_rules)
    rabbit_topology_queues: list[str] = Field(default_factory=list)

    postgres_dsn: PostgresDsn = Field(strict=True)

    @property
    def routing_destinations(self) -> set[str]:
        destinations = {self.default_rabbit_destination}
        destinations.update(rule.destination for rule in self.event_routing_rules)
        return destinations

    @property
    def topology_queues(self) -> set[str]:
        explicit = set(self.rabbit_topology_queues)
        return explicit or self.routing_destinations

    @property
    def routing(self) -> RoutingConfig:
        return RoutingConfig(
            default_destination=self.default_rabbit_destination,
            rules=self.event_routing_rules,
        )
