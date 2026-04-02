# Integration Architecture Diagrams

Диаграммы взаимодействия между event-receiver и event-saver.

---

## Current Architecture

```mermaid
sequenceDiagram
    participant Source as External Source<br/>(Booking, Jitsi, etc.)
    participant Receiver as event-receiver
    participant RMQ as RabbitMQ<br/>Topic Exchange
    participant Saver as event-saver
    participant DB as PostgreSQL

    Source->>Receiver: HTTP POST /event/booking
    Note over Receiver: Validate auth (JWT/API key)
    Note over Receiver: Parse to CloudEvent

    Receiver->>Receiver: EventRouter.resolve_routing_key()
    Note over Receiver: Match source/type patterns

    Receiver->>RMQ: Publish CloudEvent (binary)
    Note over RMQ: Headers: ce-type, ce-source,<br/>ce-id, ce-time, ce-booking_id<br/>Body: JSON payload

    RMQ->>Saver: Deliver to queue (e.g. events.booking.lifecycle)
    Note over Saver: Parse CloudEvent from binary

    Saver->>Saver: EventParser.parse()
    Note over Saver: Create ParsedEvent domain model

    Saver->>DB: INSERT INTO events (dedup check)
    Note over DB: ON CONFLICT (booking_id,<br/>event_type, source, hash)<br/>DO NOTHING

    alt Event is new
        Saver->>Saver: Extract participants
        Saver->>DB: UPSERT participants
        Saver->>Saver: Extract booking data
        Saver->>DB: UPSERT booking
        Saver->>Saver: Execute projections
        Saver->>DB: UPSERT projections
    end

    Saver-->>RMQ: ACK message
```

---

## Improved Architecture (Recommended)

```mermaid
sequenceDiagram
    participant Source as External Source
    participant Receiver as event-receiver
    participant Schemas as event-schemas<br/>(Shared Library)
    participant RMQ as RabbitMQ<br/>Topic Exchange + DLQ
    participant Saver as event-saver
    participant DB as PostgreSQL
    participant Tracing as Distributed Tracing<br/>(Jaeger/Datadog)

    Source->>Receiver: HTTP POST /event/booking<br/>(X-Trace-Id: ...)
    Note over Receiver: Extract trace_id from header

    Receiver->>Schemas: Validate payload schema
    Note over Schemas: BookingCreatedPayloadV2.validate()

    alt Validation failed
        Schemas-->>Receiver: ValidationError
        Receiver-->>Source: 400 Bad Request
    end

    Note over Receiver: Generate idempotency_key
    Note over Receiver: Create CloudEvent with extensions:<br/>- trace_id, span_id<br/>- idempotency_key<br/>- dataschema (v2)<br/>- priority

    Receiver->>RMQ: Publish (with priority)
    Note over RMQ: Headers: ce-type, ce-source,<br/>ce-trace_id, ce-idempotency_key,<br/>ce-dataschema, ce-booking_id<br/>Priority: 10 (critical)

    Receiver->>Tracing: Send span (event.published)

    RMQ->>Saver: Deliver to queue
    Note over Saver: Extract trace_id, bind to context

    Saver->>Tracing: Send span (event.received)

    Saver->>Schemas: Validate event schema
    Note over Schemas: Match dataschema version

    alt Schema validation failed
        Saver->>RMQ: NACK (requeue=false)
        RMQ->>RMQ: Move to DLQ
        Saver->>Tracing: Send span (event.validation_failed)
    end

    Saver->>DB: INSERT with idempotency_key
    Note over DB: ON CONFLICT (idempotency_key)<br/>DO NOTHING

    alt Idempotency key exists
        Note over Saver: Event already processed (skip)
        Saver->>Tracing: Send span (event.duplicate)
    else New event
        Saver->>Saver: Process participants/booking/projections
        Saver->>DB: UPSERT all data
        Saver->>Tracing: Send span (event.processed)
    end

    alt Processing error (database down)
        Saver->>RMQ: NACK (requeue=true)
        Note over RMQ: Retry with exponential backoff
    end

    Saver-->>RMQ: ACK
    Saver->>Tracing: Send span (event.completed)
```

---

## Data Flow: CloudEvents Binary Format

### Current Format

```mermaid
graph LR
    subgraph "event-receiver: CloudEvent Creation"
        A1[Parse incoming payload]
        A2[Extract booking_uid]
        A3[Create CloudEvent attributes]
        A4[to_binary CloudEvent]

        A1 --> A2
        A2 --> A3
        A3 --> A4
    end

    subgraph "RabbitMQ Message"
        B1[Headers<br/>ce-type: booking.created<br/>ce-source: booking-service<br/>ce-id: uuid<br/>ce-time: ISO8601<br/>ce-booking_id: booking-123<br/>ce-specversion: 1.0]
        B2[Body<br/>JSON payload without booking_uid]

        A4 --> B1
        A4 --> B2
    end

    subgraph "event-saver: CloudEvent Parsing"
        C1[from_http headers, body]
        C2[Extract attributes from headers]
        C3[Parse body as JSON]
        C4[Create ParsedEvent]

        B1 --> C1
        B2 --> C1
        C1 --> C2
        C1 --> C3
        C2 --> C4
        C3 --> C4
    end

    style B1 fill:#e1f5ff
    style B2 fill:#e1f5ff
```

### Improved Format (with extensions)

```mermaid
graph LR
    subgraph "event-receiver: Enhanced CloudEvent"
        A1[Parse incoming payload]
        A2[Validate schema event-schemas]
        A3[Generate trace_id, idempotency_key]
        A4[Create CloudEvent with extensions]
        A5[to_binary CloudEvent]

        A1 --> A2
        A2 --> A3
        A3 --> A4
        A4 --> A5
    end

    subgraph "RabbitMQ Message Enhanced"
        B1[Headers<br/>ce-type: booking.created<br/>ce-source: booking-service<br/>ce-id: uuid<br/>ce-time: ISO8601<br/>ce-booking_id: booking-123<br/>ce-specversion: 1.0<br/><br/>Extensions:<br/>ce-trace_id: uuid<br/>ce-span_id: uuid<br/>ce-idempotency_key: sha256<br/>ce-dataschema: v2<br/>ce-publisher_service: event-receiver<br/>ce-publisher_version: 1.0.0]
        B2[Body<br/>Validated JSON payload]

        A5 --> B1
        A5 --> B2
    end

    subgraph "event-saver: Enhanced Processing"
        C1[from_http headers, body]
        C2[Extract trace_id, bind to logs]
        C3[Validate schema via dataschema]
        C4[Check idempotency_key]
        C5[Process if new]

        B1 --> C1
        B2 --> C1
        C1 --> C2
        C1 --> C3
        C3 --> C4
        C4 --> C5
    end

    style B1 fill:#c8e6c9
    style B2 fill:#c8e6c9
```

---

## Event Routing Topology

### Current

```mermaid
graph TD
    subgraph Sources
        Booking[Booking Service]
        Jitsi[Jitsi]
        UniSender[UniSender Go]
        GetStream[GetStream]
    end

    subgraph "event-receiver"
        Router[EventRouter<br/>glob pattern matching]
    end

    subgraph "RabbitMQ Topic Exchange"
        Exchange[events exchange<br/>type: topic]
    end

    subgraph Queues
        Q1[events.booking.lifecycle]
        Q2[events.booking.reminder]
        Q3[events.chat.lifecycle]
        Q4[events.chat.activity]
        Q5[events.notification.delivery]
        Q6[events.jitsi]
        Q7[events.mail]
        Q8[events.chat]
        Q9[events.unrouted]
    end

    subgraph "event-saver Consumers"
        C1[Consumer 1]
        C2[Consumer 2]
        C3[Consumer N]
    end

    Booking --> Router
    Jitsi --> Router
    UniSender --> Router
    GetStream --> Router

    Router --> Exchange

    Exchange -->|routing_key| Q1
    Exchange -->|routing_key| Q2
    Exchange -->|routing_key| Q3
    Exchange -->|routing_key| Q4
    Exchange -->|routing_key| Q5
    Exchange -->|routing_key| Q6
    Exchange -->|routing_key| Q7
    Exchange -->|routing_key| Q8
    Exchange -->|fallback| Q9

    Q1 --> C1
    Q2 --> C1
    Q3 --> C2
    Q4 --> C2
    Q5 --> C3
    Q6 --> C3
    Q7 --> C3
    Q8 --> C3
    Q9 --> C3

    style Exchange fill:#ffd54f
    style Router fill:#81c784
```

### Improved (with DLQ & Priority)

```mermaid
graph TD
    subgraph Sources
        Booking[Booking Service]
        Jitsi[Jitsi]
        UniSender[UniSender Go]
        GetStream[GetStream]
    end

    subgraph "event-receiver"
        Router[EventRouter<br/>+ Priority Assignment]
    end

    subgraph "RabbitMQ Exchanges"
        MainExchange[events exchange<br/>type: topic]
        DLX[events.dlx<br/>Dead Letter Exchange]
    end

    subgraph "Main Queues (with priority)"
        Q1[events.booking.lifecycle<br/>priority: 10]
        Q2[events.notification.delivery<br/>priority: 7]
        Q3[events.chat.activity<br/>priority: 5]
    end

    subgraph "Dead Letter Queues"
        DLQ1[events.booking.lifecycle.dlq]
        DLQ2[events.notification.delivery.dlq]
        DLQ3[events.chat.activity.dlq]
    end

    subgraph "event-saver Consumers"
        C1[Consumer 1<br/>+ DLQ Monitor]
        C2[Consumer 2<br/>+ DLQ Monitor]
    end

    Booking --> Router
    Jitsi --> Router
    UniSender --> Router
    GetStream --> Router

    Router -->|with priority| MainExchange

    MainExchange --> Q1
    MainExchange --> Q2
    MainExchange --> Q3

    Q1 -.->|x-dead-letter-exchange| DLX
    Q2 -.->|x-dead-letter-exchange| DLX
    Q3 -.->|x-dead-letter-exchange| DLX

    DLX --> DLQ1
    DLX --> DLQ2
    DLX --> DLQ3

    Q1 --> C1
    Q2 --> C1
    Q3 --> C2

    DLQ1 -.->|manual review| C1
    DLQ2 -.->|manual review| C2
    DLQ3 -.->|manual review| C2

    style MainExchange fill:#ffd54f
    style DLX fill:#ff8a80
    style DLQ1 fill:#ffccbc
    style DLQ2 fill:#ffccbc
    style DLQ3 fill:#ffccbc
    style Router fill:#81c784
```

---

## Schema Validation Flow

```mermaid
graph TB
    subgraph "Shared Library: event-schemas"
        Schema[EventType Enum<br/>Pydantic Models<br/>Version Registry]
    end

    subgraph "event-receiver Validation"
        R1[Receive HTTP Request]
        R2[Parse incoming payload]
        R3[event_schemas.BookingCreatedV2.validate]

        R1 --> R2
        R2 --> R3
        R3 -.->|import| Schema
    end

    subgraph "event-saver Validation"
        S1[Receive from RabbitMQ]
        S2[Extract dataschema version]
        S3[event_schemas resolve model by version]
        S4[Validate payload]

        S1 --> S2
        S2 --> S3
        S3 --> S4
        S3 -.->|import| Schema
    end

    R3 -->|Valid| Publish[Publish to RabbitMQ]
    R3 -->|Invalid| Reject[400 Bad Request]

    S4 -->|Valid| Process[Process event]
    S4 -->|Invalid| DLQ[Send to DLQ]

    style Schema fill:#9fa8da
    style R3 fill:#81c784
    style S3 fill:#81c784
    style S4 fill:#81c784
```

---

## Distributed Tracing Flow

```mermaid
sequenceDiagram
    participant Client as HTTP Client
    participant Receiver as event-receiver
    participant RMQ as RabbitMQ
    participant Saver as event-saver
    participant DB as PostgreSQL
    participant Tracer as Tracing Backend<br/>(Jaeger/Datadog)

    Note over Client,Tracer: Single Request Trace

    Client->>Receiver: POST /event/booking<br/>X-Trace-Id: abc123
    activate Receiver

    Note over Receiver: Extract trace_id from header<br/>or generate new UUID

    Receiver->>Tracer: Span: http.request.received<br/>(trace_id=abc123, span_id=span1)

    Note over Receiver: Validate, transform event

    Receiver->>Tracer: Span: event.validated<br/>(trace_id=abc123, span_id=span2)

    Receiver->>RMQ: Publish CloudEvent<br/>ce-trace_id: abc123<br/>ce-span_id: span3
    deactivate Receiver

    Receiver->>Tracer: Span: event.published<br/>(trace_id=abc123, span_id=span3)

    RMQ->>Saver: Deliver message
    activate Saver

    Note over Saver: Extract ce-trace_id, ce-span_id<br/>Bind to structlog context

    Saver->>Tracer: Span: event.received<br/>(trace_id=abc123, span_id=span4,<br/>parent_span_id=span3)

    Saver->>DB: INSERT event
    Saver->>Tracer: Span: database.insert<br/>(trace_id=abc123, span_id=span5)

    Saver->>DB: Process projections
    Saver->>Tracer: Span: projections.executed<br/>(trace_id=abc123, span_id=span6)

    Saver-->>RMQ: ACK
    deactivate Saver

    Saver->>Tracer: Span: event.completed<br/>(trace_id=abc123, span_id=span7)

    Note over Tracer: All spans linked by trace_id=abc123<br/>Full request timeline visible
```

---

## Error Handling & DLQ

```mermaid
stateDiagram-v2
    [*] --> MessageReceived: Event arrives from RabbitMQ

    MessageReceived --> SchemaValidation: Parse CloudEvent

    SchemaValidation --> IdempotencyCheck: Valid schema
    SchemaValidation --> SendToDLQ: Invalid schema (non-recoverable)

    IdempotencyCheck --> ProcessEvent: New event
    IdempotencyCheck --> AckDuplicate: Duplicate (idempotency_key exists)

    ProcessEvent --> DatabaseInsert: Extract data

    DatabaseInsert --> ProjectionExecution: Insert successful
    DatabaseInsert --> RetryLater: Database error (recoverable)

    ProjectionExecution --> Completed: All projections executed
    ProjectionExecution --> RetryLater: Projection error (recoverable)

    Completed --> AckMessage: Success
    AckDuplicate --> AckMessage: Already processed

    AckMessage --> [*]

    RetryLater --> MessageReceived: NACK (requeue=true)<br/>Exponential backoff
    SendToDLQ --> DLQQueue: NACK (requeue=false)

    DLQQueue --> ManualReview: Human intervention
    ManualReview --> [*]: Fix & replay or discard

    note right of SendToDLQ
        Non-recoverable errors:
        - Schema validation failed
        - Malformed CloudEvent
        - Business logic violation
    end note

    note right of RetryLater
        Recoverable errors:
        - Database connection timeout
        - Temporary infrastructure issue
        Max retries: 3
    end note
```

---

## Deployment Architecture

```mermaid
graph TB
    subgraph "Ingress Layer"
        LB[Load Balancer]
        ER1[event-receiver<br/>Pod 1]
        ER2[event-receiver<br/>Pod 2]
        ER3[event-receiver<br/>Pod N]
    end

    subgraph "Message Broker"
        RMQ1[RabbitMQ<br/>Node 1]
        RMQ2[RabbitMQ<br/>Node 2]
        RMQ3[RabbitMQ<br/>Node 3]
    end

    subgraph "Processing Layer"
        ES1[event-saver<br/>Pod 1]
        ES2[event-saver<br/>Pod 2]
        ES3[event-saver<br/>Pod N]
    end

    subgraph "Storage Layer"
        PG1[PostgreSQL<br/>Primary]
        PG2[PostgreSQL<br/>Replica]
    end

    subgraph "Shared Libraries"
        Schemas[event-schemas<br/>PyPI Package]
    end

    subgraph "Observability"
        Logs[Centralized Logging<br/>ELK/Loki]
        Metrics[Metrics<br/>Prometheus]
        Traces[Distributed Tracing<br/>Jaeger]
    end

    LB --> ER1
    LB --> ER2
    LB --> ER3

    ER1 --> RMQ1
    ER2 --> RMQ2
    ER3 --> RMQ3

    ER1 -.->|import| Schemas
    ER2 -.->|import| Schemas
    ER3 -.->|import| Schemas

    RMQ1 <--> RMQ2
    RMQ2 <--> RMQ3
    RMQ3 <--> RMQ1

    RMQ1 --> ES1
    RMQ2 --> ES2
    RMQ3 --> ES3

    ES1 -.->|import| Schemas
    ES2 -.->|import| Schemas
    ES3 -.->|import| Schemas

    ES1 --> PG1
    ES2 --> PG1
    ES3 --> PG1

    PG1 --> PG2

    ER1 -.->|logs| Logs
    ER1 -.->|metrics| Metrics
    ER1 -.->|traces| Traces

    ES1 -.->|logs| Logs
    ES1 -.->|metrics| Metrics
    ES1 -.->|traces| Traces

    style Schemas fill:#9fa8da
    style LB fill:#81c784
    style RMQ1 fill:#ffd54f
    style RMQ2 fill:#ffd54f
    style RMQ3 fill:#ffd54f
    style PG1 fill:#4fc3f7
    style PG2 fill:#4fc3f7
```

---

## Viewing These Diagrams

1. **GitHub/GitLab** - встроенная поддержка Mermaid
2. **VS Code** - расширение "Markdown Preview Mermaid Support"
3. **IntelliJ IDEA / PyCharm** - встроенный Markdown preview
4. **Online** - [mermaid.live](https://mermaid.live/)

---

## См. также

- [SERVICE_INTEGRATION_ANALYSIS.md](../SERVICE_INTEGRATION_ANALYSIS.md) - Детальный анализ и рекомендации
- [C4_DIAGRAMS.md](C4_DIAGRAMS.md) - Внутренняя архитектура event-saver
- [ARCHITECTURE_DECISION_RECORDS.md](ARCHITECTURE_DECISION_RECORDS.md) - Архитектурные решения
