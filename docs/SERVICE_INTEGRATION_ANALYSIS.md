# Service Integration Analysis: event-receiver ↔ event-saver

## Текущая архитектура

### event-receiver (Producer)
**Роль:** Ingress-сервис для приема событий из внешних источников

**Функции:**
- HTTP endpoints для разных источников (Booking, Jitsi, UniSender, GetStream)
- Валидация авторизации (JWT, API keys, HMAC signatures)
- Нормализация в CloudEvents binary format
- Публикация в RabbitMQ topic exchange
- Routing по source/type patterns

**Текущий формат CloudEvents:**
```python
# Headers
ce-type: "booking.created"
ce-source: "booking-service"
ce-id: "uuid"
ce-time: "2024-03-01T12:00:00Z"
ce-booking_id: "booking-123"
ce-specversion: "1.0"

# Body
{
  "user": {"email": "...", "time_zone": "..."},
  "client": {"email": "...", "time_zone": "..."},
  "start_time": "...",
  "end_time": "..."
  // booking_uid удаляется из payload и переносится в ce-booking_id
}
```

### event-saver (Consumer)
**Роль:** Persistence-сервис для сохранения и проекций событий

**Функции:**
- Подписка на RabbitMQ очереди
- Парсинг CloudEvents из binary format
- Дедупликация по `(booking_id, event_type, source, md5(payload))`
- Сохранение raw events в PostgreSQL
- Построение проекций (normalized views)
- Clean Architecture с независимыми projection handlers

---

## Анализ текущего взаимодействия

### ✅ Что работает хорошо

1. **CloudEvents Standard**
   - Индустриальный стандарт для событийной архитектуры
   - Binary format эффективен для RabbitMQ
   - Хорошая совместимость между сервисами
   - Готовность к масштабированию

2. **Routing Architecture**
   - Гибкая маршрутизация через glob patterns
   - Topic exchange + routing keys
   - Разделение по типам событий (lifecycle, notifications, chat, etc.)

3. **Дедупликация**
   - Защита от duplicate events
   - Composite unique constraint в БД

4. **Structured Logging**
   - Оба сервиса используют structlog
   - Хорошая observability

### ⚠️ Проблемы и ограничения

1. **Отсутствие Schema Validation**
   - Нет типизации payload между сервисами
   - Ошибки обнаруживаются только в runtime
   - Нет автоматической генерации документации из кода

2. **Недостаточно метаданных для трейсинга**
   - Нет `trace_id` / `correlation_id`
   - Сложно отследить событие от источника до сохранения
   - Логи не связаны между сервисами

3. **Отсутствие версионирования событий**
   - event types без версий: `booking.created` (v1? v2?)
   - При изменении схемы ломается backward compatibility
   - Нет стратегии для миграции между версиями

4. **Event Type дублирование**
   - Строковые константы в обоих сервисах
   - Риск опечаток и рассинхронизации

5. **Нет idempotency key**
   - Дедупликация только по payload hash
   - При изменении payload дублируется событие
   - Нет защиты от at-least-once delivery проблем

6. **Отсутствие Dead Letter Queue стратегии**
   - Нет обработки критических ошибок
   - Events теряются при сбоях парсинга
   - Нет retry логики

7. **Все события имеют одинаковый приоритет**
   - `booking.cancelled` обрабатывается с той же скоростью что и аналитические события
   - Критичные события могут задерживаться

8. **Inconsistent booking_id usage**
   - event-receiver: удаляет `booking_uid` из payload, переносит в header
   - event-saver: ожидает в header `ce-booking_id`
   - Но для некоторых источников (GetStream) используется `channel_id`

---

## Рекомендации по улучшению

### 🎯 Priority 1: Critical (Must Have)

#### 1.1. Shared Event Schema Library

**Проблема:** Нет типизации и валидации схем между сервисами

**Решение:**
- Создать общий Python пакет `event-schemas`
- Определить Pydantic модели для всех event types
- Использовать в обоих сервисах

**Структура:**
```python
# event-schemas/event_schemas/booking.py

from pydantic import BaseModel, Field
from datetime import datetime

class BookingCreatedPayload(BaseModel):
    """CloudEvent data schema for booking.created event."""
    user: UserInfo
    client: ClientInfo
    start_time: datetime
    end_time: datetime

class UserInfo(BaseModel):
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")
    time_zone: str = Field(..., pattern=r"^[A-Za-z_]+/[A-Za-z_]+$")
```

**Использование в event-receiver:**
```python
# Валидация перед публикацией
payload = BookingCreatedPayload(**incoming.data)
await self._publisher.publish(
    source="booking-service",
    event_type=EventType.BOOKING_CREATED,
    booking_id=booking_uid,
    data=payload.model_dump(),
)
```

**Использование в event-saver:**
```python
# Валидация при получении
try:
    payload = BookingCreatedPayload(**event.data)
    booking_data = BookingDataExtractor.extract(payload)
except ValidationError as e:
    logger.error("Invalid event schema", error=e)
    # Send to DLQ
```

**Преимущества:**
- ✅ Type safety на этапе разработки
- ✅ Runtime validation
- ✅ Автоматическая генерация JSON Schema / OpenAPI docs
- ✅ Single source of truth для схем
- ✅ Легко обновлять схемы с версионированием

**Имплементация:**
```bash
# Создать новый проект
mkdir event-schemas
cd event-schemas
uv init

# pyproject.toml
[project]
name = "event-schemas"
version = "0.1.0"
dependencies = ["pydantic>=2.0"]

# Структура
event_schemas/
├── __init__.py
├── booking.py      # BookingCreated, BookingCancelled, etc.
├── chat.py         # ChatCreated, ChatMessageSent, etc.
├── notification.py # EmailSent, TelegramSent, etc.
├── meeting.py      # MeetingUrlCreated, etc.
└── types.py        # Shared types (EventType enum, UserInfo, etc.)
```

**Деплой:**
- Publish в private PyPI / Artifactory
- Или git submodule / monorepo

---

#### 1.2. Event Type Enum (Shared Constants)

**Проблема:** Event types - строковые константы, риск опечаток

**Решение:**
- Enum в `event-schemas` пакете
- Использовать везде вместо строк

```python
# event-schemas/event_schemas/types.py

from enum import Enum

class EventType(str, Enum):
    """Unified event types across all services."""

    # Booking lifecycle
    BOOKING_CREATED = "booking.created"
    BOOKING_RESCHEDULED = "booking.rescheduled"
    BOOKING_REASSIGNED = "booking.reassigned"
    BOOKING_CANCELLED = "booking.cancelled"
    BOOKING_REMINDER_SENT = "booking.reminder_sent"

    # Chat lifecycle
    CHAT_CREATED = "chat.created"
    CHAT_DELETED = "chat.deleted"
    CHAT_MESSAGE_SENT = "chat.message_sent"

    # Meeting
    MEETING_URL_CREATED = "meeting.url_created"
    MEETING_URL_DELETED = "meeting.url_deleted"

    # Notifications
    NOTIFICATION_EMAIL_SENT = "notification.email.message_sent"
    NOTIFICATION_TELEGRAM_SENT = "notification.telegram.message_sent"

    # External integrations
    UNISENDER_STATUS_CREATED = "unisender.events.v1.transactional.status.create"
    GETSTREAM_MESSAGE_NEW = "getstream.events.v1.message.new"
    # ... etc
```

**Использование:**
```python
# event-receiver
from event_schemas.types import EventType

await self._publisher.publish(
    source="booking-service",
    event_type=EventType.BOOKING_CREATED,  # ← Type safe!
    ...
)

# event-saver
from event_schemas.types import EventType

def can_handle(self, event: ParsedEvent) -> bool:
    return event.event_type == EventType.BOOKING_CREATED  # ← Type safe!
```

---

#### 1.3. Distributed Tracing (trace_id, correlation_id)

**Проблема:** Невозможно отследить событие across services

**Решение:**
- Добавить CloudEvents extensions для трейсинга
- Propagate через все сервисы

**CloudEvents spec поддерживает custom extensions:**
```python
# event-receiver: добавляем при публикации
import uuid

attributes = {
    "type": event_type,
    "source": source,
    "id": event_id or str(uuid.uuid4()),
    "time": event_time,
    "booking_id": booking_id,
    # Extensions для трейсинга
    "traceid": request_trace_id or str(uuid.uuid4()),  # ← NEW
    "spanid": str(uuid.uuid4()),  # ← NEW
    "traceparent": f"00-{trace_id}-{span_id}-01",  # W3C Trace Context
}
```

**event-saver: извлекаем и добавляем в logs:**
```python
# consumer.py
event = from_http(headers=message.headers, data=message.body)

trace_id = event.get("traceid")
span_id = event.get("spanid")

# Bind to structlog context
structlog.contextvars.bind_contextvars(
    trace_id=trace_id,
    span_id=span_id,
    event_id=event["id"],
    event_type=event["type"],
)

# Теперь все логи в этом запросе будут содержать trace_id
await self._event_store.save_event(...)
```

**Преимущества:**
- ✅ End-to-end трейсинг от HTTP request до database
- ✅ Легко найти все логи по одному событию
- ✅ Интеграция с Jaeger / Zipkin / Datadog APM
- ✅ Соответствует W3C Trace Context standard

---

#### 1.4. Event Versioning Strategy

**Проблема:** Нет версионирования событий, breaking changes ломают систему

**Решение (Option A):** Version в event type
```python
class EventType(str, Enum):
    BOOKING_CREATED_V1 = "booking.created.v1"
    BOOKING_CREATED_V2 = "booking.created.v2"
```

**Решение (Option B):** CloudEvents `dataschema` extension
```python
attributes = {
    "type": "booking.created",
    "source": "booking-service",
    "dataschema": "https://schemas.example.com/booking/created/v2.json",  # ← NEW
    ...
}
```

**Рекомендация:** Option B (dataschema)
- Более гибкий
- Соответствует CloudEvents спецификации
- type остается читаемым

**event-saver: поддержка нескольких версий:**
```python
class BookingCreatedProjection(BaseProjection):
    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type == "booking.created"

    async def handle(self, event: ParsedEvent, ...) -> tuple[str, dict]:
        schema_version = event.raw.dataschema  # Extract version

        if schema_version == "v1" or not schema_version:
            # Old format
            payload = BookingCreatedPayloadV1(**event.payload)
        elif schema_version == "v2":
            # New format with additional fields
            payload = BookingCreatedPayloadV2(**event.payload)
        else:
            raise ValueError(f"Unsupported schema version: {schema_version}")

        # Process...
```

---

#### 1.5. Idempotency Key

**Проблема:** Дедупликация по payload hash - не защищает от retry с разным payload

**Решение:**
- Добавить CloudEvents extension `idempotencykey`
- Генерируется producer (event-receiver)
- Используется consumer (event-saver) для дедупликации

```python
# event-receiver: генерируем при публикации
import hashlib

def generate_idempotency_key(
    event_type: str,
    booking_id: str,
    payload: dict,
) -> str:
    """Deterministic idempotency key for event deduplication."""
    key_data = f"{event_type}:{booking_id}:{json.dumps(payload, sort_keys=True)}"
    return hashlib.sha256(key_data.encode()).hexdigest()

attributes = {
    "type": event_type,
    "source": source,
    "booking_id": booking_id,
    "idempotencykey": generate_idempotency_key(event_type, booking_id, data),  # ← NEW
}
```

**event-saver: используем для дедупликации:**
```sql
-- Обновить unique constraint в events table
CREATE UNIQUE INDEX idx_events_idempotency
ON events (idempotency_key)
WHERE idempotency_key IS NOT NULL;

-- Fallback на старую логику если idempotency_key отсутствует
CREATE UNIQUE INDEX idx_events_legacy
ON events (booking_id, event_type, source, hash)
WHERE idempotency_key IS NULL;
```

```python
# EventRepository
async def save(self, event: ParsedEvent) -> bool:
    row = await self._sql.fetch_one("""
        INSERT INTO events (
            event_id, booking_id, event_type, source,
            hash, occurred_at, payload, idempotency_key  -- ← NEW
        )
        VALUES (
            :event_id, :booking_id, :event_type, :source,
            :hash, :occurred_at, :payload, :idempotency_key  -- ← NEW
        )
        ON CONFLICT (idempotency_key) DO NOTHING  -- ← Primary deduplication
        RETURNING event_id
    """, {
        ...
        "idempotency_key": event.raw.idempotency_key,  # ← NEW
    })
    return row is not None
```

**Преимущества:**
- ✅ Более надежная дедупликация
- ✅ Защита от at-least-once delivery
- ✅ Явный контракт между producer и consumer

---

### 🎯 Priority 2: High (Should Have)

#### 2.1. Dead Letter Queue (DLQ) Strategy

**Проблема:** События теряются при ошибках обработки

**Решение:**
- Настроить DLQ для каждой очереди
- Automatic retry с exponential backoff
- Мониторинг DLQ

**RabbitMQ topology:**
```python
# event-receiver: ensure_topology()
for queue_name in self._topology_queues:
    # Main queue
    main_queue = RabbitQueue(
        name=queue_name,
        durable=True,
        routing_key=queue_name,
        arguments={
            "x-dead-letter-exchange": "events.dlx",  # ← DLX
            "x-dead-letter-routing-key": f"{queue_name}.dlq",
        }
    )

    # Dead Letter Queue
    dlq = RabbitQueue(
        name=f"{queue_name}.dlq",
        durable=True,
        routing_key=f"{queue_name}.dlq",
        arguments={
            "x-message-ttl": 86400000,  # 24 hours retention
        }
    )

    await self._broker.declare_queue(main_queue)
    await self._broker.declare_queue(dlq)
```

**event-saver: обработка ошибок:**
```python
async def _consume_message(self, *, message: Any, queue_name: str) -> None:
    try:
        event = from_http(headers=message.headers, data=message.body)
        await self._event_store.save_event(...)

    except ValidationError as e:
        # Schema validation failed - non-recoverable
        logger.error("Invalid event schema, sending to DLQ", error=e)
        # NACK with requeue=False → goes to DLQ
        raise

    except DatabaseError as e:
        # Database issue - recoverable, retry
        logger.warning("Database error, will retry", error=e)
        # NACK with requeue=True → retry
        raise

    except Exception as e:
        # Unknown error - log and DLQ
        logger.exception("Unexpected error processing event")
        raise
```

---

#### 2.2. Event Priority

**Проблема:** Критичные события обрабатываются с той же скоростью что и аналитика

**Решение:**
- RabbitMQ priority queues
- event-receiver устанавливает priority при публикации

```python
# event-schemas: добавить priority в EventType
class EventPriority(int, Enum):
    CRITICAL = 10  # booking.cancelled, booking.created
    HIGH = 7       # notifications
    NORMAL = 5     # chat messages
    LOW = 1        # analytics, status updates

EVENT_PRIORITIES: dict[EventType, EventPriority] = {
    EventType.BOOKING_CANCELLED: EventPriority.CRITICAL,
    EventType.BOOKING_CREATED: EventPriority.CRITICAL,
    EventType.NOTIFICATION_EMAIL_SENT: EventPriority.HIGH,
    EventType.CHAT_MESSAGE_SENT: EventPriority.NORMAL,
    # ...
}
```

```python
# event-receiver: publish with priority
priority = EVENT_PRIORITIES.get(event_type, EventPriority.NORMAL)

await self._broker.publish(
    body,
    exchange=self._exchange,
    routing_key=routing_key,
    headers=headers,
    priority=priority.value,  # ← NEW
)
```

```python
# RabbitMQ queues с priority support
queue = RabbitQueue(
    name=queue_name,
    durable=True,
    routing_key=queue_name,
    arguments={
        "x-max-priority": 10,  # ← Enable priority
    }
)
```

---

#### 2.3. Content Type Support

**Проблема:** Только JSON, нет гибкости для будущего

**Решение:**
- Использовать CloudEvents `datacontenttype`
- Поддержка JSON, Protobuf (будущее)

```python
# event-receiver: указываем content type
attributes = {
    "type": event_type,
    "source": source,
    "datacontenttype": "application/json",  # ← Explicit
}
```

```python
# event-saver: проверяем перед парсингом
content_type = event.get("datacontenttype", "application/json")

if content_type == "application/json":
    payload = json.loads(event.data)
elif content_type == "application/protobuf":
    payload = parse_protobuf(event.data)
else:
    raise ValueError(f"Unsupported content type: {content_type}")
```

---

### 🎯 Priority 3: Nice to Have

#### 3.1. Event Metadata Enrichment

```python
# event-receiver: добавляем publisher metadata
attributes = {
    ...
    "publisherservice": "event-receiver",  # ← NEW
    "publisherversion": __version__,  # ← NEW
    "environment": settings.environment,  # ← NEW
}
```

#### 3.2. Monitoring & Observability

- **Metrics:**
  - event-receiver: events published counter (by type, source)
  - event-saver: events consumed counter, processing latency, DLQ size

- **Alerting:**
  - DLQ size > threshold
  - Processing latency > threshold
  - Schema validation errors spike

#### 3.3. Event Replay Capability

- Сохранять raw CloudEvents в object storage (S3)
- Возможность replay событий за период
- Полезно для debugging и data recovery

---

## Migration Plan

### Phase 1: Foundation (Week 1-2)
1. ✅ Создать `event-schemas` пакет
2. ✅ Определить Pydantic модели для всех event types
3. ✅ Определить `EventType` enum
4. ✅ Добавить в оба сервиса как dependency

### Phase 2: Schema Validation (Week 3)
1. ✅ event-receiver: валидировать payload перед публикацией
2. ✅ event-saver: валидировать при получении
3. ✅ Graceful degradation если validation fails

### Phase 3: Tracing & Idempotency (Week 4)
1. ✅ Добавить `trace_id`, `span_id` extensions
2. ✅ Добавить `idempotency_key` extension
3. ✅ Migration для БД (новая колонка + индекс)
4. ✅ Обновить event-saver для использования idempotency_key

### Phase 4: Versioning & DLQ (Week 5-6)
1. ✅ Добавить `dataschema` extension
2. ✅ Настроить DLQ topology
3. ✅ Обновить error handling в event-saver

### Phase 5: Priority & Monitoring (Week 7+)
1. ✅ Priority queues
2. ✅ Metrics & alerting
3. ✅ Documentation updates

---

## Backward Compatibility

Все изменения должны быть **backward compatible**:

1. **Новые CloudEvents extensions - optional**
   - event-saver должен работать без них
   - Graceful fallback на старую логику

2. **Idempotency key - optional**
   - Два unique indexes: новый (idempotency_key) + старый (booking_id + hash)
   - Постепенная миграция

3. **Schema validation - warn, not fail**
   - На первом этапе: логировать ошибки валидации, но не блокировать
   - После стабилизации: reject invalid events

4. **Versioning - default to v1**
   - Если `dataschema` отсутствует - считаем v1
   - event-saver поддерживает обе версии

---

## Риски и Mitigation

| Риск | Вероятность | Impact | Mitigation |
|------|-------------|--------|------------|
| Breaking changes при миграции | Medium | High | Phased rollout, feature flags, backward compatibility |
| Performance degradation от validation | Low | Medium | Benchmark, optional validation в production |
| Shared library coupling | Medium | Medium | Semver, changelog, deprecation policy |
| DLQ переполнение | Low | High | Monitoring, alerts, automatic cleanup |

---

## Заключение

**Текущая архитектура:**
- ✅ Solid foundation с CloudEvents
- ✅ Clean separation между producer/consumer
- ✅ Масштабируемая routing topology

**Критичные улучшения:**
1. ✅ Shared event schemas (type safety)
2. ✅ Distributed tracing (observability)
3. ✅ Idempotency key (reliability)
4. ✅ Event versioning (evolution)
5. ✅ DLQ strategy (resilience)

**Результат после имплементации:**
- 🎯 Type-safe интеграция между сервисами
- 🎯 End-to-end observability
- 🎯 Resilient к ошибкам (DLQ, retry)
- 🎯 Готовность к эволюции (versioning)
- 🎯 Production-ready для масштабирования

CloudEvents был правильным выбором - все рекомендуемые улучшения используют стандартные CloudEvents extensions и best practices.
