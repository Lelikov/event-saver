# Architecture Documentation

Архитектурная документация проекта event-saver.

## 📚 Документы

### [C4_DIAGRAMS.md](C4_DIAGRAMS.md)
Полный набор C4 диаграмм:
- System Context Diagram
- Container Diagram  
- Component Diagram
- Sequence Diagram
- Dependency Flow
- Projection System Architecture

**Размер:** 16 KB | **Диаграмм:** 7

### [ARCHITECTURE_DECISION_RECORDS.md](ARCHITECTURE_DECISION_RECORDS.md)
Архитектурные решения (ADR):
- ADR-001: Переход на Clean Architecture
- ADR-002: Projection Handlers как независимые классы
- ADR-003: Immutable Value Objects
- ADR-004: Repository Pattern
- ADR-005: Dishka для DI
- ADR-006: AsyncIO и asyncpg
- ADR-007: CloudEvents формат

**Размер:** 12 KB | **Решений:** 7

### [DIAGRAMS_QUICKSTART.md](DIAGRAMS_QUICKSTART.md)
Быстрый старт по работе с диаграммами:
- Как просматривать
- Как редактировать
- Синтаксис Mermaid
- Tips & Tricks

## 🏗️ Архитектура: Clean Architecture

```
┌─────────────────────────────────────────────────┐
│           Infrastructure Layer                  │
│  (Repositories, Projections, Adapters)         │
│                                                 │
│   ┌─────────────────────────────────────────┐  │
│   │      Application Layer                   │  │
│   │  (Use Cases, Orchestration)             │  │
│   │                                          │  │
│   │   ┌──────────────────────────────────┐  │  │
│   │   │     Domain Layer                 │  │  │
│   │   │  (Models, Business Logic)       │  │  │
│   │   └──────────────────────────────────┘  │  │
│   │                                          │  │
│   └─────────────────────────────────────────┘  │
│                                                 │
└─────────────────────────────────────────────────┘

Зависимости: Infrastructure → Application → Domain
```

## 🔍 Быстрая навигация

### Для новых разработчиков
1. Начните с [C4_DIAGRAMS.md](C4_DIAGRAMS.md) - Context Diagram
2. Изучите [Component Diagram](C4_DIAGRAMS.md#level-3-component-diagram)
3. Прочитайте [ADR-001](ARCHITECTURE_DECISION_RECORDS.md#adr-001-переход-на-clean-architecture)

### Для добавления функционала
1. [Sequence Diagram](C4_DIAGRAMS.md#sequence-diagram-event-ingestion-flow) - понять flow
2. [Projection System](C4_DIAGRAMS.md#projection-system-architecture) - добавить проекцию
3. [ADR-002](ARCHITECTURE_DECISION_RECORDS.md#adr-002-projection-handlers-как-независимые-классы) - паттерн проекций

### Для рефакторинга
1. [Dependency Flow](C4_DIAGRAMS.md#dependency-flow-clean-architecture) - принципы
2. [ADR-003](ARCHITECTURE_DECISION_RECORDS.md#adr-003-immutable-value-objects-для-доменных-моделей) - модели
3. [ADR-004](ARCHITECTURE_DECISION_RECORDS.md#adr-004-repository-pattern-с-чистым-crud) - repositories

## 📊 Статистика кода

```
Domain Layer:        372 строки (чистая бизнес-логика)
Application Layer:   274 строки (оркестрация)
Infrastructure:    1,325 строк (реализация)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ИТОГО:            1,971 строка
```

## 🎯 Ключевые принципы

✅ **Single Responsibility** - каждый класс делает одно
✅ **Dependency Inversion** - зависимости направлены внутрь
✅ **Immutable Models** - типизированные dataclasses
✅ **Independent Projections** - каждая проекция отдельно
✅ **Pure CRUD Repositories** - без бизнес-логики

## 🔗 См. также

- [../../README.md](../../README.md) - Главная документация
- [../../REFACTORING_SUMMARY.md](../../REFACTORING_SUMMARY.md) - История рефакторинга
- [../../CLAUDE.md](../../CLAUDE.md) - Документация для Claude Code
