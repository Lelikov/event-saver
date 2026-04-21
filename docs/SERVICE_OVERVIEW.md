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
| **event-users** | HTTP API for user lookups (proxy endpoint) | `USERS_SERVICE_URL` + `USERS_SERVICE_API_TOKEN` |

## Key Environment Variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `POSTGRES_DSN` | Yes | - | PostgreSQL connection string |
| `RABBIT_URL` | No | `amqp://guest:guest@localhost:5672/` | RabbitMQ AMQP URL |
| `RABBIT_EXCHANGE` | No | `events` | Exchange name |
| `DEFAULT_RABBIT_DESTINATION` | No | `events.unrouted` | Fallback queue |
| `RABBIT_TOPOLOGY_QUEUES` | No | (derived from routing rules) | Explicit queue list |
| `USERS_SERVICE_URL` | Yes | - | event-users base URL |
| `USERS_SERVICE_API_TOKEN` | Yes | - | Bearer token for event-users |
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
        PROJ["projections/<br/>Meeting, Email, Telegram,<br/>EmailStatusHistory, Chat,<br/>ChatReadUpdate, Video"]
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
| Adapters | `adapters/consumer.py`, `adapters/sql.py`, `adapters/publisher.py`, `adapters/users_client.py` | ~250 |
| Interfaces | `interfaces/*.py` (7 protocol files) | ~100 |
| DI/Config | `ioc.py`, `config.py`, `routing.py`, `event_types.py` | ~280 |

## Known Limitations

Source: `docs/audit/raw/event-saver_audit.md`

| Severity | Issue | Location |
|---|---|---|
| HIGH | No DLQ configured; failed messages lack retry/dead-letter path | `adapters/consumer.py:52-59` (has `x-dead-letter-exchange` arg but no matching exchange/queue declaration) |
| HIGH | Application layer imports concrete infrastructure classes | `application/use_cases/ingest_event.py:13`, `application/services/projection_executor.py:10` |
| MEDIUM | Projection failures are silently swallowed (logged, not re-raised) | `application/services/projection_executor.py:62-68` |
| MEDIUM | Deduplication hash computed with `ujson.dumps` (Python) vs. `md5(payload::text)` (Postgres) mismatch for legacy path | `domain/services/event_parser.py:82-85` |
| MEDIUM | `BookingDataExtractor` only maps two event types to status | `domain/services/booking_extractor.py:9-12` |
| MEDIUM | `declare=False` on queues means service crashes if queues do not pre-exist | `adapters/consumer.py:57` |
| LOW | No test suite exists | entire `event_saver/` |
| LOW | `EventRouter`/`CloudEventPublisher` wired in DI but never called | `ioc.py:93-109` |
| LOW | Duplicate `_parse_occurred_at` logic in consumer and domain | `adapters/consumer.py:21-29`, `domain/services/event_parser.py:70-79` |
