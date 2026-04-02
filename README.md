# Event Saver

Асинхронный сервис для приема, сохранения и обработки бизнес-событий из RabbitMQ в PostgreSQL.

[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Architecture: Clean](https://img.shields.io/badge/architecture-clean-green.svg)](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)

## 🎯 Назначение

Event Saver - это сервис для:
- 📥 Приема событий из RabbitMQ (CloudEvents формат)
- 💾 Сохранения raw событий в PostgreSQL с дедупликацией
- 🔄 Построения проекций (normalized views) для аналитики
- 📊 Предоставления исторических данных для других сервисов

## 🏗️ Архитектура

Проект построен по принципам **Clean Architecture**:

```
event_saver/
├── domain/              # 🟢 Чистая бизнес-логика (без зависимостей)
│   ├── models/         # Value objects (ParsedEvent, Participant, BookingData)
│   └── services/       # Domain services (парсинг, извлечение данных)
│
├── application/         # 🔵 Оркестрация (use cases)
│   ├── use_cases/      # IngestEventUseCase
│   └── services/       # ProjectionExecutor
│
└── infrastructure/      # 🔴 Детали реализации
    └── persistence/
        ├── repositories/    # CRUD операции (event, participant, booking)
        └── projections/     # Независимые projection handlers
```

### Ключевые принципы

✅ **Single Responsibility** - каждый класс делает одно
✅ **Dependency Inversion** - зависимости направлены внутрь (Infrastructure → Application → Domain)
✅ **Immutable Models** - типизированные dataclasses
✅ **Independent Projections** - каждая проекция = отдельный handler

📖 **Подробнее:** [C4 Diagrams](docs/architecture/C4_DIAGRAMS.md) | [ADRs](docs/architecture/ARCHITECTURE_DECISION_RECORDS.md)

## 🚀 Быстрый старт

### Требования

- Python 3.14+
- PostgreSQL 14+
- RabbitMQ 3.x

### Установка

```bash
# 1. Клонировать репозиторий
git clone <repository-url>
cd event-saver

# 2. Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# или
.venv\Scripts\activate     # Windows

# 3. Установить зависимости
uv sync
# или
pip install -e .

# 4. Настроить переменные окружения
cp .env.example .env
# Отредактировать .env

# 5. Запустить PostgreSQL (локально через Docker)
docker-compose up -d

# 6. Применить миграции
alembic upgrade head
```

### Запуск

```bash
# Development
uvicorn event_saver.main:app --reload --host 0.0.0.0 --port 8888

# Production
uvicorn event_saver.main:app --host 0.0.0.0 --port 8888 --workers 4
```

## ⚙️ Конфигурация

Настройки задаются через переменные окружения (`.env` файл):

```bash
# Обязательные
POSTGRES_DSN=postgresql+asyncpg://user:pass@localhost:5432/event_saver

# Опциональные
DEBUG=false
LOG_LEVEL=INFO
RABBIT_URL=amqp://guest:guest@localhost:5672/
RABBIT_EXCHANGE=events
DEFAULT_RABBIT_DESTINATION=events.unrouted
GETSTREAM_USER_ID_ENCRYPTION_KEY=your-key-here
```

📖 **Полный список:** см. `config.py`

## 🔧 Разработка

### Команды

```bash
# Линтинг и форматирование
ruff check --fix
ruff format

# Pre-commit hooks
pre-commit install
pre-commit run --all-files

# Миграции БД
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
```

### Структура проекта

```
event_saver/
├── domain/                  # Доменная логика
│   ├── models/             # Value objects
│   └── services/           # Domain services
├── application/             # Use cases
│   ├── use_cases/          # IngestEventUseCase
│   └── services/           # ProjectionExecutor
├── infrastructure/          # Реализация
│   └── persistence/
│       ├── repositories/   # EventRepo, ParticipantRepo, BookingRepo
│       └── projections/    # MeetingProjection, EmailProjection, etc.
├── adapters/               # Messaging adapters
│   ├── consumer.py         # RabbitMQ consumer
│   └── publisher.py        # CloudEvent publisher
├── config.py               # Settings
├── ioc.py                  # Dependency injection
├── main.py                 # Entry point
└── db/
    └── models.py           # SQLAlchemy models

alembic/
└── versions/               # Database migrations

docs/
└── architecture/
    ├── C4_DIAGRAMS.md                      # C4 диаграммы
    └── ARCHITECTURE_DECISION_RECORDS.md    # ADR документация
```

## 📊 База данных

### Основные таблицы

**`events`** - Raw события с дедупликацией
```sql
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    booking_id TEXT,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    hash TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    payload JSONB NOT NULL,
    UNIQUE (booking_id, event_type, source, hash)
);
```

**`bookings`** - Normalized booking data
**`participants`** - Организаторы и клиенты
**`booking_organizer_history`** - История назначений

### Проекции

- `booking_meeting_links` - Ссылки на встречи
- `booking_email_notifications` - Email уведомления
- `booking_telegram_notifications` - Telegram уведомления
- `booking_chat_events` - События чата
- `booking_video_events` - События видеоконференций

## 🔄 Event Flow

```mermaid
graph LR
    A[RabbitMQ] -->|CloudEvent| B[Consumer]
    B --> C[IngestEventUseCase]
    C --> D[EventParser]
    C --> E[EventRepository]
    C --> F[ParticipantExtractor]
    C --> G[BookingExtractor]
    C --> H[ProjectionExecutor]
    H --> I[Projection Handlers]
    E --> J[(PostgreSQL)]
    F --> J
    G --> J
    I --> J
```

1. **Parse** - CloudEvent → ParsedEvent (domain model)
2. **Save Raw** - INSERT в `events` с дедупликацией
3. **Extract Participants** - Извлечение и upsert участников
4. **Extract Booking** - Извлечение и upsert данных бронирования
5. **Execute Projections** - Независимые projection handlers

📖 **Подробнее:** [Sequence Diagram](docs/architecture/C4_DIAGRAMS.md#sequence-diagram-event-ingestion-flow)

## 🧪 Добавление новой проекции

Проекции - это независимые обработчики событий. Добавить новую проекцию очень легко:

### 1. Создать handler

```python
# infrastructure/persistence/projections/my_projection.py

from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.domain.models.event import ParsedEvent

class MyNewProjection(BaseProjection):
    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type == "my.new.event.type"

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        # Ваша логика
        return (
            "INSERT INTO my_table (...) VALUES (...)",
            {"param": value}
        )
```

### 2. Зарегистрировать в DI

```python
# ioc.py

@provide(scope=Scope.APP)
def provide_my_projection(self) -> MyNewProjection:
    return MyNewProjection()

@provide(scope=Scope.APP)
def provide_projection_handlers(
    self,
    # ... existing projections
    my_proj: MyNewProjection,
) -> list[BaseProjection]:
    return [
        # ... existing handlers
        my_proj,
    ]
```

Готово! 🎉

## 📚 Документация

### Проект
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) - Детальный контекст проекта (RU)
- [EVENTS_DIGEST.md](EVENTS_DIGEST.md) - Схемы payload событий
- [QUEUES_DIGEST.md](QUEUES_DIGEST.md) - Маршрутизация событий по очередям
- [REFACTORING_SUMMARY.md](REFACTORING_SUMMARY.md) - История рефакторинга
- [CLAUDE.md](CLAUDE.md) - Документация для Claude Code

### Архитектура
- [C4 Diagrams](docs/architecture/C4_DIAGRAMS.md) - Архитектурные диаграммы event-saver
- [ADRs](docs/architecture/ARCHITECTURE_DECISION_RECORDS.md) - Архитектурные решения
- [Integration Diagrams](docs/architecture/INTEGRATION_DIAGRAMS.md) - Диаграммы взаимодействия с event-receiver

### Интеграция с event-receiver
- [Integration Analysis](docs/SERVICE_INTEGRATION_ANALYSIS.md) - Детальный анализ взаимодействия (40+ страниц)
- [Improvements Summary](docs/INTEGRATION_IMPROVEMENTS_SUMMARY.md) - Краткое резюме и roadmap

## 🛠️ Технологический стек

- **Python 3.14** - Язык программирования
- **FastAPI** - Web framework + lifespan management
- **FastStream** - RabbitMQ integration
- **CloudEvents** - Стандартный формат событий (с extensions для tracing/idempotency)
- **event-schemas** - Shared event schemas library (Pydantic models)
- **SQLAlchemy 2.x (async)** - ORM
- **asyncpg** - PostgreSQL драйвер
- **Alembic** - Database migrations
- **Dishka** - Dependency injection
- **Structlog** - Structured logging (с distributed tracing support)
- **Ruff** - Linter & formatter

## 📝 Лицензия

[Укажите лицензию]

## 🤝 Контрибьюция

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

Перед коммитом:
```bash
ruff check --fix
ruff format
pre-commit run --all-files
```

## 📞 Контакты

[Укажите контактную информацию]
