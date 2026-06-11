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
- Reconcile missing participant user_ids: a periodic background task re-resolves bookings whose `organizer_user_id`/`client_user_id` is NULL via the event-users API (see "Background Tasks")

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
| **event-users** | Identity resolution for the user_id backfill (optional; only when `USER_ID_BACKFILL_ENABLED=True`) | `EVENT_USERS_API_URL` (HTTP, Bearer `EVENT_USERS_API_TOKEN`) |

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
| `USER_ID_BACKFILL_ENABLED` | No | `False` | Enable the periodic user_id backfill task |
| `USER_ID_BACKFILL_INTERVAL_SECONDS` | No | `300` | Pause between backfill cycles |
| `USER_ID_BACKFILL_BATCH_SIZE` | No | `100` | Max incomplete bookings scanned per cycle |
| `EVENT_USERS_API_URL` | When backfill enabled | `""` | event-users base URL (fail-fast validated at DI wiring) |
| `EVENT_USERS_API_TOKEN` | When backfill enabled | `""` | Static Bearer token for event-users |

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

## Background Tasks

### user_id backfill / reconciliation (audit-v2 follow-up #9)

When event-users is down at ingress, event-receiver publishes participants with
`user_id=None` and bookings are persisted with NULL `organizer_user_id` /
`client_user_id`. A periodic asyncio task (started in the app lifespan when
`USER_ID_BACKFILL_ENABLED=True`) reconciles them:

1. Selects up to `USER_ID_BACKFILL_BATCH_SIZE` bookings with a NULL participant column (`ORDER BY id`)
2. Finds the missing participant's email in the latest stored event payload (`events.payload->normalized->participants`, lateral JSONB query)
3. Resolves email+role via event-users `GET /api/users/by-identity` (Bearer token; identities are cached per cycle; the backfill never creates users)
4. Updates the booking row (`UPDATE ... WHERE id = :id AND <column> IS NULL`), commits once per cycle, and logs a summary (`scanned_bookings` / `resolved` / `unresolved` / `missing_email` / `aborted`)

On event-users transport errors (`UsersServiceUnavailableError`) the cycle is
aborted: already-resolved rows are committed, the rest wait for the next
interval (back-off by skipping the cycle). Unexpected exceptions are logged and
the loop survives. Components: `application/services/user_id_backfill.py`
(UserIdBackfillService), `adapters/users_client.py` (UsersHttpResolver),
`adapters/backfill_runner.py` (UserIdBackfillRunner), protocols in
`interfaces/user_resolver.py` / `interfaces/backfill.py`.

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
