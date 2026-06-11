# event-saver Service Overview

## Domain

Asynchronous event ingestion and projection service. Consumes CloudEvents from RabbitMQ, deduplicates, persists raw events to PostgreSQL, and builds materialized projection tables (bookings, notifications, meetings, chat, video) for downstream read services.

## Responsibilities

- Subscribe to RabbitMQ queues and consume CloudEvents messages
- Parse and normalize incoming events into domain models
- Deduplicate events (event_id PK + idempotency key, bare ON CONFLICT DO NOTHING)
- Persist raw events to the `events` table
- Extract participant UUIDs and booking metadata from payloads
- Upsert booking records and organizer history
- Execute projection handlers that materialize normalized views into dedicated tables
- Own the PostgreSQL schema: all Alembic migrations live here

## NOT Responsible For

- HTTP ingress (handled by `event-receiver`)
- Read API (handled by `event-admin`)
- User/contact management (handled by `event-users`)
- Publishing events to RabbitMQ (event-saver only consumes; it does not route)
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
| `RABBIT_PREFETCH_COUNT` | No | `10` | Consumer QoS prefetch (keep within DB pool headroom) |
| `RABBIT_GRACEFUL_TIMEOUT` | No | `30` | Seconds to drain in-flight handlers on shutdown |
| `DEBUG` | No | `False` | Enable debug mode |
| `LOG_LEVEL` | No | `INFO` | Structlog level |

Reference: `event_saver/config.py`. Queue topology comes from `event_schemas.queues.SAVER_QUEUES`.

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
| DI/Config | `ioc.py`, `config.py` | ~280 |

## HTTP Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness: process up, HTTP serving |
| GET | `/ready` | Readiness: `SELECT 1` against PostgreSQL (503 when unreachable) |

## Reliability

- **Prefetch (QoS)**: `RABBIT_PREFETCH_COUNT` (default 10) bounds concurrent handlers within DB pool headroom
- **Transient failures** (DB connectivity, pool/network timeouts): 3 in-process attempts with exponential backoff, then NACK + requeue — never dead-lettered
- **Poison messages** (parse/validation errors): rejected to `<queue>.dlq` on `events.dlx`
- **Graceful shutdown**: `RABBIT_GRACEFUL_TIMEOUT` (default 30s) drains in-flight handlers

## Known Limitations

See `docs/AUDIT.md` (audit-v2, 2026-06-11) — all findings resolved. Remaining
platform-level TODO: DLQ alerting/re-shovel tooling (DLQs carry 24h message TTL
per CONTRACT_DECISIONS D2, so unattended poison messages expire).

### Payload Structure Convention

All CloudEvent payloads from `event-receiver` use a two-level wrapper:

```json
{"original": { /* raw source payload */ }, "normalized": {"participants": [...]}}
```

Projections and classifiers MUST access source-specific fields via `payload.get("original", payload)` (fallback for backward compatibility). Domain extractors (`BookingDataExtractor`, `ParticipantExtractor`) already follow this convention. See `VideoEventProjection` as the reference implementation.
