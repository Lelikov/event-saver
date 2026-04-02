# Architecture Decision Records (ADR)

Документирование ключевых архитектурных решений в проекте event-saver.

## ADR-001: Переход на Clean Architecture

**Статус:** ✅ Принято и реализовано (2026-04-03)

**Контекст:**

Старый код страдал от следующих проблем:
- God Object `SqlEventStore` (462 строки) смешивал все: парсинг, валидацию, БД, проекции
- Процедурные функции вместо объектов
- `dict` вместо типизированных моделей
- Логика размазана по `adapters/` без четкой структуры
- Сложно тестировать и понимать код

**Решение:**

Реализовать Clean Architecture с четким разделением на слои:

1. **Domain Layer** - чистая бизнес-логика
   - Value objects (immutable dataclasses)
   - Domain services (pure functions/classes)
   - Без зависимостей от инфраструктуры

2. **Application Layer** - оркестрация
   - Use cases (IngestEventUseCase)
   - Application services (ProjectionExecutor)

3. **Infrastructure Layer** - детали реализации
   - Repositories (CRUD only)
   - Projection handlers (independent)
   - Adapters (RabbitMQ, EventStore facade)

**Последствия:**

✅ **Положительные:**
- Код стал понятнее (clear separation of concerns)
- Domain легко тестировать без БД/RabbitMQ
- Легко добавлять новые проекции (1 файл)
- Типизация через dataclasses
- Single Responsibility на каждом уровне

⚠️ **Отрицательные:**
- Код стал на ~800 строк больше (но в 10 раз понятнее)
- Требуется понимание Clean Architecture от команды
- Больше файлов (но каждый делает одно)

**Альтернативы:**

1. **Оставить как есть** - отклонено (код превратился в спагетти)
2. **Простой рефакторинг** - отклонено (не решит корневые проблемы)
3. **Микросервисы** - избыточно для текущей задачи

---

## ADR-002: Projection Handlers как независимые классы

**Статус:** ✅ Принято и реализовано (2026-04-03)

**Контекст:**

Старый подход использовал процедурные функции:
```python
def build_email_notification_statement(...):
    if event_type == EMAIL_SENT:
        # 50 строк SQL
    if event_type == UNISENDER_STATUS:
        # еще 50 строк SQL
```

Проблемы:
- Нет полиморфизма
- Сложно добавлять новые типы
- Одна функция обрабатывает несколько типов событий

**Решение:**

Каждая проекция - отдельный класс, наследующий `BaseProjection`:

```python
class EmailNotificationProjection(BaseProjection):
    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type == EMAIL_SENT

    async def handle(self, event, ...) -> tuple[str, dict]:
        # Только логика email-проекции
        return (sql, params)
```

**Последствия:**

✅ **Положительные:**
- Легко добавить новую проекцию = 1 новый файл
- Легко удалить проекцию = удалить файл + убрать из DI
- Каждая проекция независима
- Failure одной проекции не блокирует другие
- Полиморфизм через базовый класс

⚠️ **Отрицательные:**
- Больше файлов
- Нужно регистрировать каждую проекцию в DI

**Альтернативы:**

1. **Одна большая функция** - отклонено (текущий антипаттерн)
2. **Strategy pattern с registry** - избыточно, DI решает эту задачу
3. **Event-driven с обработчиками** - сложнее для данной задачи

---

## ADR-003: Immutable Value Objects для доменных моделей

**Статус:** ✅ Принято и реализовано (2026-04-03)

**Контекст:**

Старый код использовал `dict` для передачи данных:
```python
payload = {"email": "...", "role": "..."}
# Что в payload? Какие поля обязательные? 🤷
```

Проблемы:
- Нет автодополнения в IDE
- Ошибки находятся только в runtime
- Нет гарантий типов
- Можно случайно мутировать данные

**Решение:**

Использовать immutable dataclasses:

```python
@dataclass(frozen=True, slots=True)
class ParsedEvent:
    raw: RawEventData
    payload_hash: str

@dataclass(frozen=True, slots=True)
class Participant:
    email: str
    role: str | None = None
    time_zone: str | None = None
```

**Последствия:**

✅ **Положительные:**
- Автодополнение в IDE
- Проверка типов на этапе разработки (mypy, pyright)
- Immutable = безопасность от случайных изменений
- Hashable = можно использовать в set/dict
- Документация через типы

⚠️ **Отрицательные:**
- Чуть больше кода для определения классов
- Нужно создавать новые инстансы при изменении (copy with changes)

**Альтернативы:**

1. **Pydantic models** - слишком тяжеловесно, избыточная валидация
2. **NamedTuple** - нет возможности методов, менее читаемо
3. **dict с TypedDict** - только аннотации, без runtime проверок

---

## ADR-004: Repository Pattern с чистым CRUD

**Статус:** ✅ Принято и реализовано (2026-04-03)

**Контекст:**

В старом коде SQL-запросы и бизнес-логика были смешаны в одном классе.

**Решение:**

Repositories содержат только CRUD операции без бизнес-логики:

```python
class EventRepository:
    async def save(self, event: ParsedEvent) -> bool:
        # Только INSERT, без бизнес-логики
        row = await self._sql.fetch_one("""
            INSERT INTO events (...)
            VALUES (...)
            ON CONFLICT DO NOTHING
            RETURNING event_id
        """, {...})
        return row is not None
```

Вся бизнес-логика в Domain Services или Use Cases.

**Последствия:**

✅ **Положительные:**
- Repositories легко тестировать (mock ISqlExecutor)
- Можно заменить реализацию (PostgreSQL → MongoDB)
- Четкая ответственность (CRUD только)
- Переиспользование в разных use cases

⚠️ **Отрицательные:**
- Нельзя делать сложные запросы с логикой в repository
- Больше кода (отдельные классы для каждой сущности)

**Альтернативы:**

1. **Active Record** - смешивает модель и БД, сложно тестировать
2. **Data Mapper с логикой** - нарушает Single Responsibility

---

## ADR-005: Dishka для Dependency Injection

**Статус:** ✅ Принято (существующее решение)

**Контекст:**

Нужна система DI для управления зависимостями и их временем жизни.

**Решение:**

Используем Dishka - современную DI библиотеку для Python с поддержкой:
- Scopes (APP, REQUEST)
- Async dependencies
- Type hints
- Integration с FastAPI

```python
@provide(scope=Scope.APP)
def provide_event_parser(self) -> EventParser:
    return EventParser()

@provide(scope=Scope.REQUEST)
def provide_event_repository(self, sql: ISqlExecutor) -> EventRepository:
    return EventRepository(sql)
```

**Последствия:**

✅ **Положительные:**
- Автоматическое управление зависимостями
- Правильное время жизни (singleton vs per-request)
- Type-safe
- Интеграция с FastAPI

⚠️ **Отрицательные:**
- Дополнительная библиотека
- Нужно понимать концепции DI
- Сложнее отладка (зависимости создаются автоматически)

**Альтернативы:**

1. **Dependency Injector** - менее современный, хуже type hints
2. **Manual DI** - слишком много boilerplate кода
3. **FastAPI Depends** - не подходит для APP-scoped зависимостей

---

## ADR-006: AsyncIO и asyncpg для работы с БД

**Статус:** ✅ Принято (существующее решение)

**Контекст:**

Нужна высокая производительность при работе с PostgreSQL и RabbitMQ.

**Решение:**

Использовать asyncio стек:
- SQLAlchemy 2.x async
- asyncpg (драйвер PostgreSQL)
- FastStream для RabbitMQ

**Последствия:**

✅ **Положительные:**
- Высокая производительность (non-blocking I/O)
- Эффективное использование ресурсов
- Современный подход (Python 3.14)

⚠️ **Отрицательные:**
- Сложнее отладка async кода
- Нельзя использовать sync библиотеки
- Async-инфекция (все вызовы должны быть async)

**Альтернативы:**

1. **Sync код + thread pool** - хуже производительность
2. **psycopg2 sync** - не масштабируется под нагрузкой

---

## ADR-007: CloudEvents как стандартный формат событий

**Статус:** ✅ Принято (существующее решение)

**Контекст:**

Нужен стандартизированный формат для событий из разных источников.

**Решение:**

Использовать [CloudEvents](https://cloudevents.io/) спецификацию:
- Стандартные атрибуты (id, type, source, time)
- Binary mode для RabbitMQ (headers + body)
- Совместимость между сервисами

**Последствия:**

✅ **Положительные:**
- Индустриальный стандарт
- Совместимость с другими системами
- Понятная структура событий
- Библиотека для работы (`cloudevents` package)

⚠️ **Отрицательные:**
- Overhead на парсинг
- Нужна дополнительная библиотека

**Альтернативы:**

1. **Свой формат** - несовместимо с внешним миром
2. **JSON без структуры** - нет стандарта

---

## Template для новых ADR

```markdown
## ADR-XXX: Название решения

**Статус:** 🔄 Предложено / ✅ Принято / ❌ Отклонено / 🗑️ Устарело

**Контекст:**

Опишите проблему или вопрос, требующий решения.

**Решение:**

Опишите принятое решение.

**Последствия:**

✅ **Положительные:**
- ...

⚠️ **Отрицательные:**
- ...

**Альтернативы:**

1. **Альтернатива 1** - почему не выбрали
2. **Альтернатива 2** - почему не выбрали
```
