# event-saver Service Overview

## Domain

Asynchronous event ingestion and projection service. Consumes CloudEvents from RabbitMQ, deduplicates, persists raw events to PostgreSQL, and builds materialized projection tables (bookings, notifications, meetings, chat, video) for downstream read services.

## Responsibilities

- Subscribe to RabbitMQ queues and consume CloudEvents messages
- Parse and normalize incoming events into domain models
- Deduplicate events (idempotency key or payload hash)
- Persist raw events to the `events` table
- Extract participant UUIDs and booking metadata from payloads
- Upsert booking records and organizer history
- Execute projection handlers that materialize normalized views into dedicated tables
- Own the PostgreSQL schema: all Alembic migrations live here

## NOT Responsible For

- HTTP ingress (handled by `event-receiver`)
- Read API (handled by `event-admin`)
- User/contact management (handled by `event-users`)
- Publishing events to RabbitMQ for other consumers (the wired `EventRouter`/`CloudEventPublisher` is unused)
- Frontend concerns

## Runtime Dependencies

| Dependency | Role | Connection |
|---|---|---|
| **RabbitMQ** | Message broker (consumer) | `RABBIT_URL` (AMQP), topic exchange `events` |
| **PostgreSQL** | Persistent store (owner/writer) | `POSTGRES_DSN` (asyncpg) |

## Key Environment Variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `POSTGRES_DSN` | Yes | - | PostgreSQL connection string |
| `RABBIT_URL` | No | `amqp://guest:guest@localhost:5672/` | RabbitMQ AMQP URL |
| `RABBIT_EXCHANGE` | No | `events` | Exchange name |
| `DEFAULT_RABBIT_DESTINATION` | No | `events.unrouted` | Fallback queue |
| `RABBIT_TOPOLOGY_QUEUES` | No | (derived from routing rules) | Explicit queue list |
| `GETSTREAM_USER_ID_ENCRYPTION_KEY` | No | - | Decrypt GetStream user IDs |
| `DEBUG` | No | `False` | Enable debug mode |
| `LOG_LEVEL` | No | `INFO` | Structlog level |

Reference: `event_saver/config.py:93-144`

## Clean Architecture Layer Map

```mermaid
graph TB
    subgraph Entry["Entry Points"]
        MAIN["main.py<br/>(FastAPI lifespan)"]
        CONSUMER["adapters/consumer.py<br/>RabbitEventConsumerRunner"]
    end

    subgraph Interfaces["Interfaces (Protocols)"]
        IES["IEventStore"]
        ISQL["ISqlExecutor / ISqlExecutorFactory"]
        ICR["IEventConsumerRunner"]
        IBC["IBookingEventClassifier"]
    end

    subgraph Application["Application Layer"]
        UC["use_cases/ingest_event.py<br/>IngestEventUseCase"]
        PE["services/projection_executor.py<br/>ProjectionExecutor"]
    end

    subgraph Domain["Domain Layer (pure logic)"]
        EP["services/event_parser.py<br/>EventParser"]
        PX["services/participant_extractor.py<br/>ParticipantExtractor"]
        BX["services/booking_extractor.py<br/>BookingDataExtractor"]
        ME["models/event.py<br/>ParsedEvent, RawEventData"]
        MB["models/booking.py<br/>BookingData"]
    end

    subgraph Infrastructure["Infrastructure Layer"]
        FACADE["persistence/event_store_facade.py<br/>CleanArchitectureEventStore"]
        ER["repositories/event_repository.py<br/>EventRepository"]
        BR["repositories/booking_repository.py<br/>BookingRepository"]
        PROJ["projections/<br/>Meeting, Email, Telegram,<br/>EmailStatusHistory, Chat,<br/>ChatReadUpdate, Video, Lifecycle"]
        SQL["adapters/sql.py<br/>SqlExecutor"]
    end

    subgraph DI["Dependency Injection"]
        IOC["ioc.py<br/>AppProvider (Dishka)"]
    end

    MAIN --> ICR
    CONSUMER --> IES
    FACADE --> UC
    UC --> EP & PX & BX & ER & BR & PE
    PE --> PROJ
    PE --> ISQL
    IOC --> MAIN

    style Domain fill:#e8f5e9
    style Application fill:#e3f2fd
    style Infrastructure fill:#fff3e0
    style Entry fill:#fce4ec
```

### File-to-Layer Mapping

| Layer | Files | Lines (approx) |
|---|---|---|
| Entry | `main.py:1-78` | 78 |
| Domain models | `domain/models/event.py`, `domain/models/booking.py` | 89 |
| Domain services | `domain/services/event_parser.py`, `participant_extractor.py`, `booking_extractor.py` | 145 |
| Application | `application/use_cases/ingest_event.py`, `application/services/projection_executor.py` | 200 |
| Infrastructure | `infrastructure/persistence/` (facade, repositories, projections) | ~1300 |
| Adapters | `adapters/consumer.py`, `adapters/sql.py` | ~150 |
| Interfaces | `interfaces/*.py` (7 protocol files) | ~100 |
| DI/Config | `ioc.py`, `config.py`, `routing.py`, `event_types.py` | ~280 |

## Known Limitations

Source: `docs/audit/raw/event-saver_audit.md`

| Severity | Issue | Location | Status |
|---|---|---|---|
| MEDIUM | `BookingDataExtractor` only maps two event types to status | `domain/services/booking_extractor.py:9-12` | Open (by design: COALESCE preserves existing) |
| LOW | No test suite exists for projections | `tests/` | Open |
| ~~HIGH~~ | ~~Application layer imports concrete classes~~ | - | Resolved 2026-04-21 |
| ~~HIGH~~ | ~~No DLQ configured~~ | - | Resolved 2026-04-21 |
| ~~MEDIUM~~ | ~~Projection failures silently swallowed~~ | - | Resolved 2026-04-21 |
| ~~MEDIUM~~ | ~~Deduplication hash mismatch~~ | - | Resolved 2026-04-21 |
| ~~CRITICAL~~ | ~~Projections read payload from wrong level (NULL values)~~ | - | Resolved 2026-04-22 |
| ~~MEDIUM~~ | ~~MeetingLinkProjection ignores url_deleted~~ | - | Resolved 2026-04-22 |
| ~~MEDIUM~~ | ~~BookingTimelineClassifier reads getstream type from wrong level~~ | - | Resolved 2026-04-22 |

### Payload Structure Convention

All CloudEvent payloads from `event-receiver` use a two-level wrapper:

```json
{"original": { /* raw source payload */ }, "normalized": {"participants": [...]}}
```

Projections and classifiers MUST access source-specific fields via `payload.get("original", payload)` (fallback for backward compatibility). Domain extractors (`BookingDataExtractor`, `ParticipantExtractor`) already follow this convention. See `VideoEventProjection` as the reference implementation.
