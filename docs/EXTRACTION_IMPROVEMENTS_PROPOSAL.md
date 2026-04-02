# Proposal: Улучшение Extraction Logic

## 🎯 Проблема

**Текущая ситуация:**

```python
# В use_case - if-ы по source
def _extract_participants(self, event):
    if event.source == SourceType.BOOKING:
        return self._participant_extractor.extract_from_booking_event(...)
    if event.source == SourceType.UNISENDER_GO:
        return self._participant_extractor.extract_from_unisender_event(...)
    if event.source == SourceType.GETSTREAM:
        return self._participant_extractor.extract_from_getstream_event(...)
    if event.source == SourceType.JITSI:
        return self._participant_extractor.extract_from_jitsi_event(...)
    return []

# В каждом extractor методе - дублирование парсинга
def extract_from_booking_event(self, payload: dict):
    users = payload.get("users")
    if not isinstance(users, list):
        return []
    for user in users:
        if not isinstance(user, dict):
            continue
        email = user.get("email")
        if not isinstance(email, str) or not email:
            continue
        # ... еще 20 строк проверок
```

**Проблемы:**
- ❌ Много if-ов для dispatch по source/type
- ❌ Дублирование кода валидации (isinstance checks)
- ❌ Не используем event-schemas с Pydantic моделями
- ❌ Сложно добавить новый source (нужно менять use_case + extractor)
- ❌ Нет type safety при извлечении данных

---

## 💡 Предлагаемые решения

### Подход 1: Normalized Metadata в CloudEvent (Рекомендуется)

**Идея:** receiver нормализует данные и добавляет стандартные поля

#### В event-receiver

```python
# При публикации добавляем normalized metadata
def normalize_booking_event(payload: dict) -> dict:
    """Normalize booking event to standard structure."""
    return {
        "original": payload,  # Оригинальные данные (для backward compatibility)
        "normalized": {       # Стандартизированная структура
            "participants": [
                {
                    "email": payload["user"]["email"],
                    "role": "organizer",
                    "time_zone": payload["user"]["time_zone"],
                },
                {
                    "email": payload["client"]["email"],
                    "role": "client",
                    "time_zone": payload["client"]["time_zone"],
                },
            ],
            "booking": {
                "start_time": payload["start_time"],
                "end_time": payload["end_time"],
                "status": "created",
            }
        }
    }

# Публикация
await publisher.publish(
    event_type=EventType.BOOKING_CREATED,
    data=normalize_booking_event(original_payload),
)
```

#### В event-saver

```python
# Extractors стали простыми
class ParticipantExtractor:
    def extract(self, payload: dict) -> list[Participant]:
        """Extract from normalized structure."""
        normalized = payload.get("normalized", {})
        participants_data = normalized.get("participants", [])

        return [
            Participant(
                email=p["email"],
                role=p.get("role"),
                time_zone=p.get("time_zone"),
            )
            for p in participants_data
            if isinstance(p, dict) and "email" in p
        ]

# Use case стал проще - нет if-ов!
participants = self._participant_extractor.extract(event.payload)
```

**Преимущества:**
- ✅ Убрали все if-ы по source в saver
- ✅ Единая структура для всех sources
- ✅ receiver контролирует нормализацию
- ✅ Backward compatible (храним original)
- ✅ Легко добавить новый source

**Недостатки:**
- ⚠️ Дублирование данных (original + normalized)
- ⚠️ Нужно обновить receiver для всех sources

---

### Подход 2: Использовать event-schemas в saver

**Идея:** Валидировать payload через Pydantic и извлекать из typed models

```python
# В event-saver
from event_schemas import BookingCreatedPayload, ChatCreatedPayload
from event_schemas.types import EventType

class TypedParticipantExtractor:
    """Extract participants using validated Pydantic models."""

    def extract(self, event_type: str, payload: dict) -> list[Participant]:
        """Extract using type-safe Pydantic models."""
        try:
            if event_type == EventType.BOOKING_CREATED.value:
                validated = BookingCreatedPayload(**payload)
                return [
                    Participant(
                        email=validated.user.email,
                        role="organizer",
                        time_zone=validated.user.time_zone,
                    ),
                    Participant(
                        email=validated.client.email,
                        role="client",
                        time_zone=validated.client.time_zone,
                    ),
                ]

            elif event_type == EventType.CHAT_CREATED.value:
                validated = ChatCreatedPayload(**payload)
                # Extract from validated model
                return self._extract_from_chat(validated)

            # ... other types

        except ValidationError:
            # Fallback to old logic or return empty
            return []

        return []
```

**Преимущества:**
- ✅ Type safety через Pydantic
- ✅ Автоматическая валидация
- ✅ Убираем ручные isinstance checks
- ✅ IDE autocomplete работает

**Недостатки:**
- ⚠️ Все еще нужны if-ы по event_type
- ⚠️ Нужно обновлять код при добавлении нового event type
- ⚠️ Дублирование: и в receiver и в saver валидация

---

### Подход 3: Strategy Pattern с Registry

**Идея:** Каждый event type регистрирует свою стратегию extraction

```python
# event_saver/domain/services/extraction_strategies.py

from abc import ABC, abstractmethod
from event_schemas import BookingCreatedPayload, ChatCreatedPayload
from event_schemas.types import EventType

class ExtractionStrategy(ABC):
    """Base strategy for extracting data from events."""

    @abstractmethod
    def extract_participants(self, payload: dict) -> list[Participant]:
        """Extract participants from payload."""

    @abstractmethod
    def extract_booking_data(self, booking_id: str, payload: dict) -> BookingData | None:
        """Extract booking data from payload."""


class BookingCreatedStrategy(ExtractionStrategy):
    """Strategy for booking.created events."""

    def extract_participants(self, payload: dict) -> list[Participant]:
        validated = BookingCreatedPayload(**payload)
        return [
            Participant(
                email=validated.user.email,
                role="organizer",
                time_zone=validated.user.time_zone,
            ),
            Participant(
                email=validated.client.email,
                role="client",
                time_zone=validated.client.time_zone,
            ),
        ]

    def extract_booking_data(self, booking_id: str, payload: dict) -> BookingData:
        validated = BookingCreatedPayload(**payload)
        return BookingData(
            booking_id=booking_id,
            start_time=validated.start_time,
            end_time=validated.end_time,
            status="created",
        )


class ChatCreatedStrategy(ExtractionStrategy):
    """Strategy for chat.created events."""

    def extract_participants(self, payload: dict) -> list[Participant]:
        # No participants in chat.created
        return []

    def extract_booking_data(self, booking_id: str, payload: dict) -> None:
        # No booking data in chat.created
        return None


# Registry
EXTRACTION_STRATEGIES: dict[EventType, ExtractionStrategy] = {
    EventType.BOOKING_CREATED: BookingCreatedStrategy(),
    EventType.BOOKING_CANCELLED: BookingCancelledStrategy(),
    EventType.CHAT_CREATED: ChatCreatedStrategy(),
    # ... register all event types
}


# Usage in use_case
class IngestEventUseCase:
    async def execute(self, ...):
        # ...

        # Get strategy for this event type
        strategy = EXTRACTION_STRATEGIES.get(event.event_type)

        if strategy:
            participants = strategy.extract_participants(event.payload)
            booking_data = strategy.extract_booking_data(event.booking_id, event.payload)
        else:
            # Fallback
            participants = []
            booking_data = None
```

**Преимущества:**
- ✅ Убрали if-ы из use_case (dispatch через registry)
- ✅ Каждый event type - отдельный класс (Single Responsibility)
- ✅ Легко добавить новый event type (1 новый класс + 1 строка в registry)
- ✅ Type safety через Pydantic
- ✅ Тестировать проще (каждая стратегия отдельно)

**Недостатки:**
- ⚠️ Больше файлов/классов
- ⚠️ Нужно создать стратегию для каждого event type

---

## 🏆 Рекомендация

**Комбинация Подхода 1 + Подхода 2:**

### Phase 1: Добавить normalized metadata (Подход 1)

**В event-receiver** добавляем нормализацию:

```python
# event_receiver/normalizers.py

from event_schemas import BookingCreatedPayload, EventType

def normalize_event(event_type: EventType, payload: dict) -> dict:
    """Normalize event payload to standard structure."""

    normalized = {}

    if event_type == EventType.BOOKING_CREATED:
        validated = BookingCreatedPayload(**payload)
        normalized = {
            "participants": [
                {
                    "email": validated.user.email,
                    "role": "organizer",
                    "time_zone": validated.user.time_zone,
                },
                {
                    "email": validated.client.email,
                    "role": "client",
                    "time_zone": validated.client.time_zone,
                },
            ],
            "booking": {
                "start_time": validated.start_time.isoformat(),
                "end_time": validated.end_time.isoformat(),
                "status": "created",
            }
        }

    # ... other event types

    return {
        "original": payload,      # Backward compatibility
        "normalized": normalized,  # Standard structure
    }


# В publisher
await self._publisher.publish(
    event_type=EventType.BOOKING_CREATED,
    booking_id=booking_uid,
    data=normalize_event(EventType.BOOKING_CREATED, payload_dict),
    trace_id=trace_id,
)
```

**В event-saver** используем normalized:

```python
# event_saver/domain/services/participant_extractor.py

class ParticipantExtractor:
    """Extract participants from normalized CloudEvent payload."""

    def extract(self, payload: dict) -> list[Participant]:
        """Extract from normalized structure with fallback to original."""

        # Try normalized first
        normalized = payload.get("normalized", {})
        participants_data = normalized.get("participants", [])

        if participants_data:
            return [
                Participant(
                    email=p["email"],
                    role=p.get("role"),
                    time_zone=p.get("time_zone"),
                )
                for p in participants_data
                if isinstance(p, dict) and "email" in p
            ]

        # Fallback to original structure (backward compatibility)
        return self._extract_from_original(payload.get("original", payload))

    def _extract_from_original(self, payload: dict) -> list[Participant]:
        """Legacy extraction logic."""
        # Keep old logic for backward compatibility
        # ... existing code
```

### Phase 2: Постепенная миграция

1. **Week 1:** Добавить normalized в receiver для booking events
2. **Week 2:** Обновить saver для чтения normalized (с fallback)
3. **Week 3:** Добавить normalized для остальных event types
4. **Week 4:** После проверки удалить fallback логику

---

## 📊 Comparison

| Feature | Current | Подход 1 (Normalized) | Подход 2 (Pydantic) | Подход 3 (Strategy) |
|---------|---------|---------------------|-------------------|-------------------|
| If-ы в use_case | ❌ Много | ✅ Нет | ⚠️ Есть | ✅ Нет |
| Type safety | ❌ Нет | ⚠️ Частично | ✅ Да | ✅ Да |
| Backward compatible | ✅ Да | ✅ Да | ⚠️ Сложно | ⚠️ Сложно |
| Легко добавить новый type | ❌ Сложно | ✅ Легко | ⚠️ Средне | ✅ Легко |
| Дублирование данных | ✅ Нет | ⚠️ Да (original+normalized) | ✅ Нет | ✅ Нет |
| Effort для migration | - | 🟢 Low | 🟡 Medium | 🔴 High |

---

## 🎯 Action Plan (Рекомендуемый)

### Step 1: Добавить Normalizers в event-receiver

```bash
# Создать файл
event_receiver/normalizers.py

# Функции:
- normalize_booking_created()
- normalize_booking_cancelled()
- normalize_chat_created()
- ... etc
```

### Step 2: Интегрировать в Publisher

```python
# event_receiver/controllers/ingest.py

# Before publishing
normalized_data = normalize_event(event_type, payload)

await self._publisher.publish(
    event_type=event_type,
    data=normalized_data,  # ← Contains both original + normalized
    ...
)
```

### Step 3: Обновить Extractors в event-saver

```python
# event_saver/domain/services/participant_extractor.py

class ParticipantExtractor:
    def extract(self, payload: dict) -> list[Participant]:
        # Try normalized first
        if "normalized" in payload:
            return self._extract_from_normalized(payload["normalized"])

        # Fallback to legacy
        return self._extract_from_legacy(payload)
```

### Step 4: Постепенно удалить legacy код

После того как все events идут с normalized - удалить fallback логику.

---

## 💬 Вопросы для обсуждения

1. **Дублирование данных:** Готовы ли мы хранить и original и normalized?
   - Альтернатива: хранить только normalized (breaking change)

2. **Миграция:** Делать постепенно или сразу все event types?
   - Рекомендация: постепенно (меньше риск)

3. **Стоит ли добавлять Strategy pattern потом?**
   - Можно сделать Phase 3 после normalized
   - Strategy будет проще с normalized структурой

---

## ✅ Recommended Approach

**Start with Подход 1 (Normalized Metadata):**

1. ✅ Минимальные изменения
2. ✅ Backward compatible
3. ✅ Убирает if-ы из saver
4. ✅ Централизует нормализацию в receiver
5. ✅ Можно мигрировать постепенно

**Later add Подход 3 (Strategy)** если понадобится еще большая гибкость.

---

Что думаешь? Какой подход больше нравится?
