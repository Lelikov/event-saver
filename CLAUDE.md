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
    participant.py         # Participant
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
      participant_repository.py
      booking_repository.py
    projections/           # Independent event handlers
      meeting_projection.py
      notification_projection.py
      chat_projection.py
      video_projection.py
    event_store_facade.py  # Adapter for IEventStore interface

  messaging/               # In adapters/ for now
    consumer.py           # RabbitMQ consumer
    publisher.py          # CloudEvent publisher
```

### Key Principles

1. **Domain Layer** - No infrastructure dependencies, pure Python + dataclasses
2. **Application Layer** - Orchestrates domain services and repositories
3. **Infrastructure Layer** - Implements interfaces, handles I/O
4. **Dependency Direction** - Always points inward (infrastructure → application → domain)

### Dependency Injection (Dishka)

Dependencies are wired through `ioc_new.py` (NewAppProvider):
- `Scope.APP` - Singleton services (settings, domain services, projections)
- `Scope.REQUEST` - Per-request (repositories with session)

When adding new features:
1. Domain models in `domain/models/`
2. Business logic in `domain/services/`
3. Repository in `infrastructure/persistence/repositories/`
4. Projection handler in `infrastructure/persistence/projections/`
5. Wire in `ioc_new.py`

### Event Flow (Refactored Clean Architecture)

**IngestEventUseCase orchestrates the entire flow:**

1. **Parse** - `EventParser` converts CloudEvent → `ParsedEvent` (domain model)
2. **Save Raw Event** - `EventRepository.save()` with deduplication
3. **Extract Participants** - `ParticipantExtractor` → `ParticipantRepository.upsert()`
4. **Extract Booking Data** - `BookingDataExtractor` → `BookingRepository.upsert()`
5. **Execute Projections** - `ProjectionExecutor` runs all applicable handlers:
   - `MeetingLinkProjection` → booking_meeting_links
   - `EmailNotificationProjection` → booking_email_notifications
   - `TelegramNotificationProjection` → booking_telegram_notifications
   - `ChatEventProjection` → booking_chat_events
   - `VideoEventProjection` → booking_video_events
   - Each projection is independent and can be added/removed easily

### Event Deduplication

Events are deduplicated using a composite unique constraint:
- `(booking_id, event_type, source, md5(payload::text))`
- If an identical event is received, `ON CONFLICT DO NOTHING` prevents duplicate storage
- Only the first occurrence of each unique event is saved

### Event Routing

`EventRouter` (in `routing.py`) routes events to specific RabbitMQ queues based on configurable rules:
- Supports glob patterns (`fnmatch`) for `source_pattern` and `type_pattern`
- First matching rule wins
- Falls back to `default_rabbit_destination` if no rules match
- Default rules route to queues like:
  - `events.booking.lifecycle` - booking created/cancelled/reassigned
  - `events.chat.activity` - chat messages
  - `events.notification.delivery` - email/telegram notifications
  - `events.jitsi` - Jitsi meeting events
  - `events.unrouted` - fallback queue

## Configuration

Settings are loaded from `.env` file via Pydantic Settings (`config.py`):

**Required**:
- `POSTGRES_DSN` - PostgreSQL connection string (must be valid `PostgresDsn`)

**Optional**:
- `DEBUG` - enable debug mode (default: `False`)
- `LOG_LEVEL` - logging level (default: `INFO`)
- `RABBIT_URL` - RabbitMQ AMQP URL (default: `amqp://guest:guest@localhost:5672/`)
- `RABBIT_EXCHANGE` - exchange name (default: `events`)
- `DEFAULT_RABBIT_DESTINATION` - fallback queue (default: `events.unrouted`)
- `RABBIT_TOPOLOGY_QUEUES` - explicit list of queues to subscribe to
- `GETSTREAM_USER_ID_ENCRYPTION_KEY` - key for decrypting GetStream user IDs

Event routing rules have defaults but can be overridden via environment variables.

## Database Schema

### Core Tables

**`events`** - Raw event storage
- Primary key: `event_id` (text)
- Unique constraint: `(booking_id, event_type, source, hash)`
- Indexes: `(booking_id, occurred_at DESC)`, `(event_type, occurred_at DESC)`
- `hash` column: `md5(payload::text)` for deduplication

**`bookings`** - Normalized booking data
- Primary key: `id` (bigserial)
- Unique: `booking_uid`
- Tracks: status, organizer, client, start/end times, first/last seen

**`participants`** - Users (organizer/client)
- Primary key: `id` (bigserial)
- Unique: `email`
- Tracks: role, timezone

**`booking_organizer_history`** - Organizer reassignment audit trail

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
- Headers: `ce-type`, `ce-source`, `ce-id`, `ce-time`, `ce-booking_id`, `ce-specversion`
- Body: Event payload (data)

The consumer (`adapters/consumer.py`) uses `from_http(headers=..., data=...)` to parse incoming messages.

### Projection System

Event projections are built via `IEventProjectionStatementFactory`:
- Separate builders for different event categories (interactions, notifications, etc.)
- Builders return lists of SQL statements executed in a transaction
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

- Consumer logs exceptions and re-raises (FastStream handles retry/dead-letter)
- Raw event insertion failures are logged with event metadata
- Projection failures are caught to prevent blocking raw event storage

## Important Files

### Entry Points
- `main.py` - Application entry point, lifespan management
- `config.py` - Settings and routing rules
- `ioc_new.py` - **New DI container with clean architecture**

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

### Legacy (To be removed)
- `adapters/event_store.py` - Old monolithic event store
- `ioc.py` - Old DI container

## Documentation Files

- `PROJECT_CONTEXT.md` - Detailed project context (Russian)
- `EVENTS_DIGEST.md` - Event payload schemas
- `QUEUES_DIGEST.md` - Queue routing reference and event-to-queue mapping
- `REFACTORING_SUMMARY.md` - Complete refactoring summary (before/after)
- `docs/architecture/C4_DIAGRAMS.md` - C4 architecture diagrams (Context, Container, Component)
- `docs/architecture/ARCHITECTURE_DECISION_RECORDS.md` - Key architectural decisions (ADRs)
