# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**event-saver** is an asynchronous event ingestion service that consumes CloudEvents from RabbitMQ and persists them to PostgreSQL with automatic deduplication. Built with FastAPI, FastStream, SQLAlchemy 2.x (async), and Dishka for dependency injection.

The service subscribes to RabbitMQ queues, normalizes incoming CloudEvents, saves raw events to the database, and builds event projections (normalized views of bookings, participants, notifications, etc.) for analytics and auditing.

## Technology Stack

- **Python 3.14** with async/await patterns throughout
- **FastAPI** for application lifecycle and DI integration
- **FastStream (RabbitMQ)** for message broker integration
- **CloudEvents** (`cloudevents` library) for standardized event format
- **SQLAlchemy 2.x async** + **asyncpg** for database access
- **Alembic** for database migrations
- **Dishka** for dependency injection container
- **Structlog** for structured logging
- **Ruff** for linting and formatting
- **pre-commit** hooks for code quality

## Development Commands

### Running the Application

```bash
# Run locally (requires PostgreSQL and RabbitMQ)
uvicorn event_saver.main:app --host 0.0.0.0 --port 8888 --reload

# With custom log config
uvicorn event_saver.main:app --host 0.0.0.0 --port 8888 --log-config uvicorn_config.json

# Start local PostgreSQL
docker-compose up -d
```

### Database Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Create new migration (auto-generate from model changes)
alembic revision --autogenerate -m "description of changes"

# Downgrade one revision
alembic downgrade -1

# View migration history
alembic history
```

### Code Quality

```bash
# Run ruff linter with auto-fix
ruff check --fix

# Format code
ruff format

# Run all pre-commit hooks
pre-commit run --all-files

# Install pre-commit hooks
pre-commit install
```

## Architecture

### Clean Architecture (Domain-Driven Design)

The codebase follows clean architecture principles with strict layering:

```
domain/                     # Pure business logic (no dependencies)
  models/                   # Value objects (immutable, typed)
    event.py               # ParsedEvent, RawEventData
    booking.py            # BookingData
  services/                # Domain services (business logic)
    event_parser.py        # Parse CloudEvents → domain models
    participant_extractor.py  # Extract participants from payloads
    booking_extractor.py   # Extract booking data

application/               # Use cases (orchestration)
  use_cases/
    ingest_event.py       # Main ingestion flow
  services/
    projection_executor.py  # Execute projection handlers

infrastructure/            # Implementation details
  persistence/
    repositories/          # Data access (pure CRUD)
      event_repository.py
      booking_repository.py
    projections/           # Independent event handlers
      meeting_projection.py
      notification_projection.py
      chat_projection.py
      video_projection.py
    event_store_facade.py  # Adapter for IEventStore interface

  messaging/               # In adapters/ for now
    consumer.py           # RabbitMQ consumer (retry/DLQ classification)
```

### Key Principles

1. **Domain Layer** - No infrastructure dependencies, pure Python + dataclasses
2. **Application Layer** - Orchestrates domain services and repositories
3. **Infrastructure Layer** - Implements interfaces, handles I/O
4. **Dependency Direction** - Always points inward (infrastructure → application → domain)

### Architecture Notes

- Application layer depends only on protocols from `interfaces/` — no direct infrastructure imports
- `IEventRepository`, `IBookingRepository` — repository abstractions
- `IProjectionHandler` — projection handler abstraction (replaces direct `BaseProjection` import)

### Dependency Injection (Dishka)

Dependencies are wired through `ioc.py` (AppProvider):
- `Scope.APP` - Singleton services (settings, domain services, projections)
- `Scope.REQUEST` - Per-request (repositories with session)

When adding new features:
1. Domain models in `domain/models/`
2. Business logic in `domain/services/`
3. Repository in `infrastructure/persistence/repositories/`
4. Projection handler in `infrastructure/persistence/projections/`
5. Wire in `ioc.py`

### Event Flow (Refactored Clean Architecture)

**IngestEventUseCase orchestrates the entire flow:**

1. **Parse** - `EventParser` converts CloudEvent → `ParsedEvent` (domain model)
2. **Save Raw Event** - `EventRepository.save()` with deduplication
3. **Extract Participants** - `ParticipantExtractor` resolves organizer/client UUIDs from `normalized.participants`
4. **Extract Booking Data** - `BookingDataExtractor` → `BookingRepository.upsert()`
5. **Execute Projections** - `ProjectionExecutor` runs all applicable handlers:
   - `MeetingLinkProjection` → booking_meeting_links
   - `EmailNotificationProjection` → booking_email_notifications
   - `TelegramNotificationProjection` → booking_telegram_notifications
   - `ChatEventProjection` / `ChatReadUpdateProjection` → booking_chat_events
   - `VideoEventProjection` → booking_video_events
   - `LifecycleProjection` → booking_lifecycle_events (created/rescheduled/reassigned/cancelled/rejected/client_reassigned)
   - Each projection is independent and can be added/removed easily

### Event Deduplication

A single `INSERT ... ON CONFLICT DO NOTHING` (no named target) suppresses every
unique violation:
- `event_id` primary key — broker redelivery of the same CloudEvent
- `idx_events_idempotency` partial unique index on `idempotency_key` — the
  deterministic key set by event-receiver (`ce-idempotencykey`)

The `hash` column (`md5(json.dumps(payload, sort_keys=True, ensure_ascii=False))`)
is informational metadata only; the legacy `(booking_id, event_type, source, hash)`
unique index was dropped in migration `a9d4c1f0b7e2`.

### Queue Subscriptions

event-saver does not route events — it only consumes. The queue set, bindings
and arguments come from `event_schemas.queues.SAVER_QUEUES` (single source of
truth): `events.booking.lifecycle.saver`, `events.chat.lifecycle`,
`events.chat.activity`, `events.chat`, `events.meeting.lifecycle`,
`events.notification.delivery`, `events.jitsi`, `events.mail`,
`events.unrouted`. The consumer idempotently declares `events.dlx` and its own
`<queue>.dlq` companions at startup (no startup-order dependency on
event-receiver).

## Configuration

Settings are loaded from `.env` file via Pydantic Settings (`config.py`):

**Required**:
- `POSTGRES_DSN` - PostgreSQL connection string (must be valid `PostgresDsn`)

**Optional**:
- `DEBUG` - enable debug mode (default: `False`)
- `LOG_LEVEL` - logging level (default: `INFO`)
- `RABBIT_URL` - RabbitMQ AMQP URL (default: `amqp://guest:guest@localhost:5672/`)
- `RABBIT_EXCHANGE` - exchange name (default: `events`)
- `RABBIT_PREFETCH_COUNT` - consumer QoS prefetch (default: `10`, keep within DB pool headroom)
- `RABBIT_GRACEFUL_TIMEOUT` - seconds to drain in-flight handlers on shutdown (default: `30`)

Queues/bindings/arguments are NOT configurable — they come from `event_schemas.queues.SAVER_QUEUES`.

## Database Schema

### Core Tables

**`events`** - Raw event storage
- Primary key: `event_id` (text)
- Partial unique index on `idempotency_key` (`idx_events_idempotency`)
- Indexes: `(booking_id, occurred_at DESC)`, `(event_type, occurred_at DESC)`, partial on `trace_id`
- `hash` column: informational payload digest (not used for dedup)

**`bookings`** - Normalized booking data
- Primary key: `id` (bigserial)
- Unique: `booking_uid`
- Tracks: status (`created`/`cancelled`/`rejected`), organizer/client UUIDs
  (references event-users), start/end times, first/last seen

**`booking_lifecycle_events`** - Booking timeline (action + details per lifecycle event)

**`booking_organizer_history`** - Organizer reassignment audit trail

There is no `participants` table — participants were replaced by
`organizer_user_id`/`client_user_id` UUID columns (migration `28bba7523965`).

### Migration Chain

Migrations are in `alembic/versions/`:
1. `9bb09c895183` - Initial events table
2. `5f1c2e9a8b1d` - Add hash column for deduplication
3. `3a791de67f88` - Make booking_id nullable
4. `b2c4f8a1d9e3` - Add booking projection tables
5. Additional migrations for projections (chat, notifications, meetings, etc.)

## Key Implementation Notes

### CloudEvents Format

All messages use CloudEvents binary mode:
- Headers: `ce-type`, `ce-source`, `ce-id`, `ce-time`, `ce-bookingid`, `ce-specversion` (plus `ce-idempotencykey`, `ce-traceid`, `ce-spanid`)
- Body: Event payload (data)

The consumer (`adapters/consumer.py`) uses `from_http(headers=..., data=...)` to parse incoming messages.

### Projection System

Event projections are built via `BaseProjection` handlers:
- Each projection handles specific event types (meetings, notifications, chat, video)
- Handlers return SQL statement + params, executed by `ProjectionExecutor`
- Statements are parameterized to prevent SQL injection
- Projection updates are idempotent where possible

### Async Patterns

All I/O operations use async/await:
- Database queries via `AsyncSession`
- RabbitMQ operations via `RabbitBroker`
- Lifespan management via `@asynccontextmanager`

When adding new features:
- Use `async def` for any method that does I/O
- Always use `async with` for session management
- Prefer `await sql.fetch_one()` / `fetch_all()` over raw session queries for consistency

### Error Handling

- **Transient errors** (DB connectivity, pool/network timeouts): retried
  in-process with exponential backoff (3 attempts), then NACK + requeue —
  the broker redelivers; the message is never dead-lettered
- **Poison messages** (CloudEvent parse errors, validation failures): rejected
  immediately to `<queue>.dlq` on `events.dlx`
- Projection failures are logged with full context and re-raised (the whole
  message transaction rolls back)

## Important Files

### Entry Points
- `main.py` - Application entry point, lifespan management
- `config.py` - Settings (Pydantic)
- `ioc.py` - **DI container with clean architecture**

### Domain Layer (Business Logic)
- `domain/models/` - Immutable value objects
- `domain/services/` - Pure business logic services

### Application Layer (Orchestration)
- `application/use_cases/ingest_event.py` - **Main event ingestion use case**
- `application/services/projection_executor.py` - Projection handler executor

### Infrastructure Layer (Implementation)
- `infrastructure/persistence/repositories/` - Data access (CRUD only)
- `infrastructure/persistence/projections/` - Independent projection handlers
- `infrastructure/persistence/event_store_facade.py` - IEventStore adapter

## Documentation Files

- `PROJECT_CONTEXT.md` - Detailed project context (Russian)
- `EVENTS_DIGEST.md` - Event payload schemas
- `QUEUES_DIGEST.md` - Queue routing reference and event-to-queue mapping
- `docs/architecture/C4_DIAGRAMS.md` - C4 architecture diagrams (Context, Container, Component)
- `docs/architecture/ARCHITECTURE_DECISION_RECORDS.md` - Key architectural decisions (ADRs)

## Service Documentation

- `docs/SERVICE_OVERVIEW.md` — architecture, maturity, known issues
- `docs/API_CONTRACTS.md` — HTTP endpoints, request/response schemas
- `docs/DATA_MODEL.md` — database tables, indexes, constraints
- `docs/DEPENDENCIES.md` — external service dependencies and failure modes
- `docs/AUDIT.md` — audit findings for this service

Cross-service architecture docs (message contracts, system topology, onboarding) are in `../docs/`.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.

## Documentation Requirements

All code changes MUST include corresponding documentation updates:
- New features or architectural changes → update relevant `docs/` files
- New event types or queue changes → update `QUEUES_DIGEST.md` and `EVENTS_DIGEST.md`
- Changed interfaces or DI wiring → update Architecture section in this file
- Bug fixes for audit findings → update `docs/AUDIT.md` to close the finding
- Migration changes → update `docs/DATA_MODEL.md`
