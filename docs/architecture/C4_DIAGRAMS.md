# C4 Architecture Diagrams

C4 модель документирует архитектуру event-saver на 4 уровнях абстракции.

## Level 1: System Context Diagram

Показывает event-saver в контексте внешних систем и пользователей.

```mermaid
C4Context
    title System Context Diagram - Event Saver

    Person(admin, "System Administrator", "Monitors and maintains the system")

    System(event_saver, "Event Saver", "Ingests, persists, and processes business events from message broker")

    System_Ext(booking_service, "Booking Service", "Publishes booking lifecycle events")
    System_Ext(notification_service, "Notification Service", "Publishes notification events")
    System_Ext(chat_service, "Chat Service (GetStream)", "Publishes chat events")
    System_Ext(video_service, "Video Service (Jitsi)", "Publishes video conference events")
    System_Ext(email_service, "Email Service (Unisender)", "Publishes email delivery status events")

    System_Ext(rabbitmq, "RabbitMQ", "Message broker for event distribution")
    SystemDb_Ext(postgres, "PostgreSQL", "Event storage and projections")

    System_Ext(analytics, "Analytics/BI Tools", "Consumes processed events")

    Rel(booking_service, rabbitmq, "Publishes events", "CloudEvents/AMQP")
    Rel(notification_service, rabbitmq, "Publishes events", "CloudEvents/AMQP")
    Rel(chat_service, rabbitmq, "Publishes events", "CloudEvents/AMQP")
    Rel(video_service, rabbitmq, "Publishes events", "CloudEvents/AMQP")
    Rel(email_service, rabbitmq, "Publishes events", "CloudEvents/AMQP")

    Rel(event_saver, rabbitmq, "Subscribes to queues", "AMQP")
    Rel(event_saver, postgres, "Persists events and projections", "SQL/asyncpg")

    Rel(analytics, postgres, "Queries events", "SQL")
    Rel(admin, event_saver, "Monitors", "Logs/Metrics")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="2")
```

---

## Level 2: Container Diagram

Показывает основные контейнеры внутри event-saver.

```mermaid
C4Container
    title Container Diagram - Event Saver

    Container_Boundary(event_saver, "Event Saver") {
        Container(api, "FastAPI Application", "Python 3.14, FastAPI", "HTTP API and application lifecycle")
        Container(consumer, "RabbitMQ Consumer", "FastStream", "Consumes events from message queues")
        Container(use_case, "Ingest Event Use Case", "Python", "Orchestrates event processing flow")
        Container(domain, "Domain Layer", "Python", "Pure business logic and models")
        Container(infrastructure, "Infrastructure Layer", "Python", "Repositories, projections, adapters")
        Container(di_container, "DI Container", "Dishka", "Manages dependencies and scopes")
    }

    System_Ext(rabbitmq, "RabbitMQ", "Message Broker")
    SystemDb(postgres, "PostgreSQL", "Event Store")

    Rel(rabbitmq, consumer, "Delivers messages", "AMQP")
    Rel(consumer, use_case, "Invokes", "Python async")
    Rel(use_case, domain, "Uses", "Python")
    Rel(use_case, infrastructure, "Uses", "Python async")
    Rel(infrastructure, postgres, "Reads/Writes", "SQL/asyncpg")
    Rel(di_container, api, "Provides dependencies", "Python")
    Rel(di_container, consumer, "Provides dependencies", "Python")
    Rel(di_container, use_case, "Provides dependencies", "Python")

    UpdateLayoutConfig($c4ShapeInRow="2", $c4BoundaryInRow="1")
```

---

## Level 3: Component Diagram

Показывает внутреннюю структуру event-saver (Clean Architecture).

```mermaid
C4Component
    title Component Diagram - Event Saver (Clean Architecture)

    Container_Boundary(domain_layer, "Domain Layer") {
        Component(models, "Domain Models", "Dataclasses", "ParsedEvent, Participant, BookingData - immutable value objects")
        Component(event_parser, "Event Parser", "Service", "Parses CloudEvents into domain models")
        Component(participant_extractor, "Participant Extractor", "Service", "Extracts participants from payloads")
        Component(booking_extractor, "Booking Data Extractor", "Service", "Extracts booking data from events")
    }

    Container_Boundary(application_layer, "Application Layer") {
        Component(ingest_use_case, "IngestEventUseCase", "Use Case", "Orchestrates entire event ingestion flow")
        Component(projection_executor, "ProjectionExecutor", "Service", "Executes projection handlers")
    }

    Container_Boundary(infrastructure_layer, "Infrastructure Layer") {
        Component(event_repo, "EventRepository", "Repository", "CRUD for raw events table")
        Component(participant_repo, "ParticipantRepository", "Repository", "CRUD for participants table")
        Component(booking_repo, "BookingRepository", "Repository", "CRUD for bookings table")

        Component(meeting_proj, "MeetingLinkProjection", "Handler", "Projects meeting links")
        Component(email_proj, "EmailNotificationProjection", "Handler", "Projects email notifications")
        Component(telegram_proj, "TelegramNotificationProjection", "Handler", "Projects telegram notifications")
        Component(chat_proj, "ChatEventProjection", "Handler", "Projects chat events")
        Component(video_proj, "VideoEventProjection", "Handler", "Projects video events")

        Component(event_store_facade, "EventStoreFacade", "Adapter", "Adapts use case to IEventStore interface")
        Component(consumer, "RabbitConsumer", "Adapter", "Consumes messages from RabbitMQ")
    }

    SystemDb(postgres, "PostgreSQL", "Database")
    System_Ext(rabbitmq, "RabbitMQ", "Message Broker")

    ' Domain dependencies (none - pure logic)
    Rel(event_parser, models, "Creates")
    Rel(participant_extractor, models, "Creates")
    Rel(booking_extractor, models, "Creates")

    ' Application depends on domain
    Rel(ingest_use_case, event_parser, "Uses")
    Rel(ingest_use_case, participant_extractor, "Uses")
    Rel(ingest_use_case, booking_extractor, "Uses")
    Rel(ingest_use_case, event_repo, "Uses")
    Rel(ingest_use_case, participant_repo, "Uses")
    Rel(ingest_use_case, booking_repo, "Uses")
    Rel(ingest_use_case, projection_executor, "Uses")

    ' Projection executor uses handlers
    Rel(projection_executor, meeting_proj, "Executes")
    Rel(projection_executor, email_proj, "Executes")
    Rel(projection_executor, telegram_proj, "Executes")
    Rel(projection_executor, chat_proj, "Executes")
    Rel(projection_executor, video_proj, "Executes")

    ' Infrastructure depends on database
    Rel(event_repo, postgres, "SQL INSERT")
    Rel(participant_repo, postgres, "SQL UPSERT")
    Rel(booking_repo, postgres, "SQL UPSERT")
    Rel(meeting_proj, postgres, "SQL UPSERT")
    Rel(email_proj, postgres, "SQL UPSERT")
    Rel(telegram_proj, postgres, "SQL UPSERT")
    Rel(chat_proj, postgres, "SQL INSERT/UPDATE")
    Rel(video_proj, postgres, "SQL INSERT")

    ' Adapters
    Rel(event_store_facade, ingest_use_case, "Delegates to")
    Rel(consumer, event_store_facade, "Calls")
    Rel(rabbitmq, consumer, "Delivers events")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

---

## Sequence Diagram: Event Ingestion Flow

Показывает последовательность обработки одного события.

```mermaid
sequenceDiagram
    participant RabbitMQ
    participant Consumer as RabbitConsumer
    participant Facade as EventStoreFacade
    participant UseCase as IngestEventUseCase
    participant Parser as EventParser
    participant EventRepo as EventRepository
    participant PartExtractor as ParticipantExtractor
    participant PartRepo as ParticipantRepository
    participant BookExtractor as BookingDataExtractor
    participant BookRepo as BookingRepository
    participant ProjExec as ProjectionExecutor
    participant Projections as Projection Handlers
    participant DB as PostgreSQL

    RabbitMQ->>Consumer: Deliver CloudEvent message
    Consumer->>Facade: save_event(queue, event_id, type, ...)

    Note over Facade: Create session & dependencies
    Facade->>UseCase: execute(event_id, type, ...)

    rect rgb(200, 220, 250)
        Note over UseCase,Parser: Step 1: Parse Event
        UseCase->>Parser: parse(event_id, type, ...)
        Parser-->>UseCase: ParsedEvent (domain model)
    end

    rect rgb(220, 250, 220)
        Note over UseCase,DB: Step 2: Save Raw Event
        UseCase->>EventRepo: save(event)
        EventRepo->>DB: INSERT with deduplication
        DB-->>EventRepo: inserted=True
        EventRepo-->>UseCase: inserted=True
    end

    alt Event is duplicate
        EventRepo-->>UseCase: inserted=False
        Note over UseCase: Skip further processing
    end

    rect rgb(250, 240, 200)
        Note over UseCase,DB: Step 3: Process Participants
        UseCase->>PartExtractor: extract(event)
        PartExtractor-->>UseCase: List[Participant]

        loop For each participant
            UseCase->>PartRepo: upsert_if_changed(participant)
            PartRepo->>DB: INSERT ... ON CONFLICT DO UPDATE
            DB-->>PartRepo: participant_id
            PartRepo-->>UseCase: participant_id
        end
    end

    rect rgb(250, 220, 220)
        Note over UseCase,DB: Step 4: Process Booking
        UseCase->>BookRepo: get_or_none(booking_id, queue)
        BookRepo->>DB: SELECT id FROM bookings

        alt Booking needs upsert
            BookRepo-->>UseCase: None
            UseCase->>BookExtractor: extract(booking_id, type, payload)
            BookExtractor-->>UseCase: BookingData

            UseCase->>BookRepo: upsert(booking_data, organizer_id, client_id)
            BookRepo->>DB: INSERT ... ON CONFLICT DO UPDATE
            DB-->>BookRepo: booking_ref_id
            BookRepo-->>UseCase: booking_ref_id

            opt If event requires organizer history
                UseCase->>BookRepo: save_organizer_history(...)
                BookRepo->>DB: INSERT INTO booking_organizer_history
            end
        end
    end

    rect rgb(230, 200, 250)
        Note over UseCase,DB: Step 5: Execute Projections
        UseCase->>ProjExec: execute_projections(event, booking_ref_id, ...)

        loop For each handler
            ProjExec->>Projections: can_handle(event)?

            alt Handler can process event
                Projections-->>ProjExec: True
                ProjExec->>Projections: handle(event, booking_ref_id, ...)
                Projections-->>ProjExec: (sql, params)
                ProjExec->>DB: Execute SQL statement
                DB-->>ProjExec: Success
            end
        end

        ProjExec-->>UseCase: Done
    end

    UseCase-->>Facade: Done
    Note over Facade: Commit transaction
    Facade->>DB: COMMIT
    Facade-->>Consumer: Success
    Consumer-->>RabbitMQ: ACK message
```

---

## Dependency Flow (Clean Architecture)

Показывает направление зависимостей (всегда внутрь).

```mermaid
graph TD
    subgraph "Infrastructure Layer"
        Consumer[RabbitMQ Consumer]
        Facade[Event Store Facade]
        Repos[Repositories]
        Projs[Projection Handlers]
    end

    subgraph "Application Layer"
        UseCase[Ingest Event Use Case]
        ProjExec[Projection Executor]
    end

    subgraph "Domain Layer"
        Models[Domain Models]
        Services[Domain Services]
    end

    subgraph "External"
        RabbitMQ[(RabbitMQ)]
        PostgreSQL[(PostgreSQL)]
    end

    RabbitMQ --> Consumer
    Consumer --> Facade
    Facade --> UseCase

    UseCase --> Services
    UseCase --> Repos
    UseCase --> ProjExec

    Services --> Models
    ProjExec --> Projs

    Repos --> PostgreSQL
    Projs --> PostgreSQL

    style Models fill:#90EE90
    style Services fill:#90EE90
    style UseCase fill:#87CEEB
    style ProjExec fill:#87CEEB
    style Repos fill:#FFB6C1
    style Projs fill:#FFB6C1
    style Consumer fill:#FFB6C1
    style Facade fill:#FFB6C1

    classDef external fill:#DDD,stroke:#999
    class RabbitMQ,PostgreSQL external
```

**Ключевой принцип:** Зависимости всегда направлены внутрь:
- 🔴 Infrastructure → Application → Domain
- ✅ Domain ← Application ← Infrastructure

---

## Projection System Architecture

Показывает как работает система проекций.

```mermaid
graph LR
    subgraph "Event Processing"
        Event[ParsedEvent]
    end

    subgraph "Projection Executor"
        ProjExec[ProjectionExecutor]
    end

    subgraph "Independent Projection Handlers"
        Meeting[MeetingLinkProjection]
        Email[EmailNotificationProjection]
        Telegram[TelegramNotificationProjection]
        Chat[ChatEventProjection]
        Video[VideoEventProjection]
        ChatRead[ChatReadUpdateProjection]
    end

    subgraph "Database Tables"
        MeetingTable[(booking_meeting_links)]
        EmailTable[(booking_email_notifications)]
        TelegramTable[(booking_telegram_notifications)]
        ChatTable[(booking_chat_events)]
        VideoTable[(booking_video_events)]
        EmailHistory[(booking_email_status_history)]
    end

    Event --> ProjExec

    ProjExec -->|can_handle?| Meeting
    ProjExec -->|can_handle?| Email
    ProjExec -->|can_handle?| Telegram
    ProjExec -->|can_handle?| Chat
    ProjExec -->|can_handle?| Video
    ProjExec -->|can_handle?| ChatRead

    Meeting -->|handle| MeetingTable
    Email -->|handle| EmailTable
    Email -->|handle| EmailHistory
    Telegram -->|handle| TelegramTable
    Chat -->|handle| ChatTable
    ChatRead -->|UPDATE| ChatTable
    Video -->|handle| VideoTable

    style ProjExec fill:#87CEEB
    style Meeting fill:#FFB6C1
    style Email fill:#FFB6C1
    style Telegram fill:#FFB6C1
    style Chat fill:#FFB6C1
    style Video fill:#FFB6C1
    style ChatRead fill:#FFB6C1
```

**Особенности:**
- Каждая проекция независима
- Проекция решает сама: `can_handle(event)` → `handle(event)`
- Failure одной проекции не блокирует другие
- Легко добавить новую проекцию

---

## Repository Pattern

Показывает паттерн Repository для доступа к данным.

```mermaid
classDiagram
    class ISqlExecutor {
        <<interface>>
        +fetch_one(sql, params)
        +execute(sql, params)
    }

    class EventRepository {
        -ISqlExecutor sql
        +save(event: ParsedEvent) bool
    }

    class ParticipantRepository {
        -ISqlExecutor sql
        +upsert(participant: Participant) int
        +find_by_email(email: str) Participant
        +upsert_if_changed(participant) int
    }

    class BookingRepository {
        -ISqlExecutor sql
        +upsert(booking_data, occurred_at, ...) int
        +find_by_booking_uid(uid: str) int
        +save_organizer_history(...)
    }

    class SqlExecutor {
        -AsyncSession session
        +fetch_one(sql, params)
        +execute(sql, params)
    }

    class AsyncSession {
        <<SQLAlchemy>>
    }

    ISqlExecutor <|.. SqlExecutor
    SqlExecutor --> AsyncSession
    EventRepository --> ISqlExecutor
    ParticipantRepository --> ISqlExecutor
    BookingRepository --> ISqlExecutor

    note for EventRepository "Pure CRUD operations\nNo business logic"
    note for ParticipantRepository "Pure CRUD operations\nNo business logic"
    note for BookingRepository "Pure CRUD operations\nNo business logic"
```

**Принципы:**
- Repositories - только CRUD
- Вся бизнес-логика в Domain Services
- Зависимость от интерфейса (ISqlExecutor), не от реализации

---

## View these diagrams

1. **GitHub/GitLab** - поддерживают Mermaid natively
2. **VS Code** - установить расширение "Markdown Preview Mermaid Support"
3. **IntelliJ IDEA** - встроенная поддержка Mermaid в Markdown
4. **Online** - https://mermaid.live/

---

## Useful Links

- [C4 Model](https://c4model.com/)
- [Mermaid Documentation](https://mermaid.js.org/)
- [Clean Architecture](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
