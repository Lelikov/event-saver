# PROJECT CONTEXT — event-saver

## 1) Назначение проекта

**event-saver** — сервис на FastAPI + RabbitMQ + PostgreSQL, который:

- подписывается на сообщения из RabbitMQ (в формате CloudEvent),
- парсит и нормализует события,
- сохраняет их в PostgreSQL,
- выполняет дедупликацию на уровне БД по комбинации `(booking_id, event_type, source, hash(payload))`.

Основной сценарий: устойчивое сохранение входящих событий для дальнейшего анализа/поиска/аудита.

---

## 2) Технологический стек

- **Python 3.14**
- **FastAPI** (жизненный цикл приложения, DI-интеграция)
- **FastStream (RabbitMQ)** для работы с брокером
- **CloudEvents** (`cloudevents`) для формата входящих/исходящих событий
- **SQLAlchemy 2.x (async)** + **asyncpg**
- **Alembic** для миграций БД
- **Dishka** для dependency injection
- **Structlog** + stdlib logging для структурированных логов
- **ujson** для сериализации payload

Зависимости и их версии описаны в `pyproject.toml`.

---

## 3) Структура проекта

```text
event_saver/
  main.py                 # точка входа FastAPI
  config.py               # настройки из env + правила маршрутизации
  ioc.py                  # DI-контейнер и провайдеры
  routing.py              # логика выбора routing key
  logger.py               # настройка логирования
  adapters/
    consumer.py           # Rabbit consumer runner
    publisher.py          # публикация CloudEvent + управление topology
    event_store.py        # запись событий в БД
    sql.py                # SQL executor поверх AsyncSession
  interfaces/
    *.py                  # Protocol-интерфейсы
  db/
    base.py               # Declarative Base
    models.py             # SQLAlchemy модель Event

alembic/
  env.py                  # конфиг Alembic (читает DSN из Settings)
  versions/*.py           # миграции схемы

Dockerfile
docker-compose.yml        # локальный Postgres
```

---

## 4) Архитектура и слои

Проект построен в стиле "ports & adapters":

- **interfaces/** — контракты (Protocol):
  - `IEventConsumerRunner`
  - `IEventStore`
  - `ICloudEventPublisher`
  - `ITopologyManager`
  - `IEventRouter`
  - `ISqlExecutor`

- **adapters/** — инфраструктурные реализации контрактов:
  - RabbitMQ consumer/publisher/topology
  - SQL persistence

- **core-конфигурация/оркестрация**:
  - `config.py` — runtime-конфиг
  - `routing.py` — правила маршрутизации
  - `ioc.py` — сборка графа зависимостей

Это упрощает замену инфраструктуры при сохранении интерфейсов.

---

## 5) Runtime flow (как сервис работает)

1. При старте `main.py`:
   - создаётся DI-контейнер Dishka,
   - читаются `Settings`,
   - настраивается логирование,
   - запускается `IEventConsumerRunner`.

2. `RabbitEventConsumerRunner.start()`:
   - регистрирует подписчики на очереди из `settings.topology_queues`,
   - запускает `RabbitBroker`.

3. На каждое сообщение:
   - сообщение конвертируется в CloudEvent через `from_http(...)`,
   - извлекаются `id`, `booking_id`, `type`, `source`, `time`, `data`,
   - вызывается `IEventStore.save_event(...)`.

4. `SqlEventStore` вставляет запись в `events`:
   - `hash = md5(payload::text)`,
   - `ON CONFLICT (booking_id, event_type, source, hash) DO NOTHING`.

Итог: повторные дубликаты одного и того же события (по бизнес-ключу + хешу payload) не сохраняются повторно.

---

## 6) Конфигурация (Settings)

`event_saver/config.py` (источник: env + `.env`):

- `debug: bool` (default: `False`)
- `log_level: str` (default: `INFO`)
- `rabbit_url: AmqpDsn` (default: `amqp://guest:guest@localhost:5672/`)
- `rabbit_exchange: str` (default: `events`)
- `default_rabbit_destination: str` (default: `events.unrouted`)
- `event_routing_rules: list[RouteRule]` (есть дефолтные правила)
- `rabbit_topology_queues: list[str]` (опциональные явные очереди)
- `postgres_dsn: PostgresDsn` (**обязательный**)

Вычисляемые свойства:

- `routing_destinations` = default destination + все destination из правил
- `topology_queues` = `rabbit_topology_queues`, либо `routing_destinations`, если список пуст
- `routing` = `RoutingConfig(default_destination, rules)`

---

## 7) Маршрутизация событий

`EventRouter` (`routing.py`) выбирает routing key по правилам `RouteRule`:

- поддерживаются glob-шаблоны (`fnmatch`) для `source_pattern` и `type_pattern`,
- первое совпавшее правило побеждает,
- если нет совпадений — используется `default_destination`.

Дефолтные правила:

- `unisender-go` + `unisender.*` -> `events.mail`
- `getstream` + `getstream.*` -> `events.message`

---

## 8) Модель данных и миграции

### Таблица `events`

Поля (`event_saver/db/models.py`):

- `event_id` (PK, text)
- `booking_id` (text, nullable)
- `event_type` (text, not null)
- `source` (text, not null)
- `hash` (text, not null)
- `occurred_at` (timestamptz, not null)
- `received_at` (timestamptz, default `now()`)
- `payload` (JSONB, not null)

Индексы:

- `ix_events_booking_id_occurred_at_desc`
- `ix_events_event_type_occurred_at_desc`
- `uq_events_booking_id_event_type_source_hash` (unique)

### Цепочка миграций

1. `9bb09c895183_create_events_table`
   - создаёт `events` + базовые индексы.
2. `5f1c2e9a8b1d_add_hash_to_events`
   - добавляет `hash`,
   - бэкфилл `hash = md5(payload::text)`,
   - удаляет исторические дубли,
   - добавляет unique-index для дедупликации.
3. `3a791de67f88_change_booking_id_to_nullable`
   - делает `booking_id` nullable.

---

## 9) Dependency Injection (Dishka)

`AppProvider` (`ioc.py`) предоставляет:

- `Settings`
- Rabbit-инфраструктуру: `RabbitRouter`, `RabbitBroker`, `RabbitExchange`
- `IEventRouter` (`EventRouter`)
- `ICloudEventPublisher` (`CloudEventPublisher`)
- `ITopologyManager` (`RabbitTopologyManager`)
- Async DB engine + sessionmaker + session
- `ISqlExecutor` (`SqlExecutor`)
- `IEventStore` (`SqlEventStore`)
- `IEventConsumerRunner` (`RabbitEventConsumerRunner`)

Области видимости:

- `Scope.APP` — singleton-подобные зависимости
- `Scope.REQUEST` — сессия/SQL executor

---

## 10) Логирование

`logger.py` настраивает:

- timestamp, level, logger name, callsite metadata,
- JSON-логирование в production-режиме,
- human-readable console renderer в debug-режиме.

Используется `structlog` + стандартный `logging`.

---

## 11) Инфраструктура и запуск

### Docker

`Dockerfile`:

- base image `python:3.14.0`,
- зависимости ставятся через `uv sync`,
- код копируется в `/opt/admin`,
- запускается: `uvicorn admin.main:app --host 0.0.0.0 --port 8888 --log-config uvicorn_config.json`.

### Локальная БД

`docker-compose.yml` поднимает PostgreSQL с healthcheck.

---

## 12) Важные замечания по текущему состоянию

1. В `main.py` есть лог `"RabbitMQ topology ensured"`, но явного вызова
   `ITopologyManager.ensure_topology()` в жизненном цикле нет.
   Если очереди/биндинги не создаются внешним процессом, топология может не быть подготовлена автоматически.

2. `SqlEventStore.save_event` в сигнатуре принимает `booking_id: str`,
   при этом фактически в consumer передаётся `event.get("booking_id")`, что может быть `None`.
   С точки зрения runtime это работает (колонка nullable), но тип стоит синхронизировать до `str | None`.

3. `README.md` в репозитории отсутствует — текущий документ фактически закрывает роль общего контекста проекта.

---

## 13) Краткое резюме

`event-saver` — асинхронный ingestion-сервис событий из RabbitMQ в PostgreSQL с дедупликацией и настраиваемой маршрутизацией. Код организован через интерфейсы и адаптеры, зависимостями управляет DI-контейнер Dishka, схема БД поддерживается Alembic-миграциями.
