# event-saver Audit Findings

Audited: 2026-04-20

---

## CRITICAL

---

[CRITICAL] `main.py` imports the legacy `ioc.py` — `ioc_new.py` does not exist

Services affected: event-saver
Location: `event_saver/main.py:17`, `event_saver/ioc.py`
Description: `main.py` imports `AppProvider` from `event_saver.ioc`. According to CLAUDE.md and REFACTORING_SUMMARY.md, `ioc.py` is the "legacy" file and `ioc_new.py` is the "new DI container with clean architecture". However, `ioc_new.py` does not exist anywhere in the repository — it was never created. The file called `ioc.py` IS in fact the clean-architecture provider (it wires `CleanArchitectureEventStore`, `IngestEventUseCase`, etc.). The CLAUDE.md documentation is contradictory: it lists `ioc.py` as "Legacy (To be removed)" while simultaneously noting that `ioc_new.py` is the file to use. In reality `ioc.py` is the live, current, fully-functional DI container. There is no stale old IoC provider at all.
Recommendation: Remove all documentation references to `ioc_new.py` being the correct file and to `ioc.py` being "legacy". Update CLAUDE.md lines 121, 130, 258 to reference `ioc.py` directly. The actual legacy file to worry about is the `adapters/event_store.py` mentioned in docs — which also does not exist in the codebase (already deleted per REFACTORING_SUMMARY.md). Clarify and clean up all docs that call `ioc.py` legacy.

---

[CRITICAL] `SqlExecutor.execute()` commits inside the method — causes double-commit / data inconsistency

Services affected: event-saver
Location: `event_saver/adapters/sql.py:18-20`, `event_saver/infrastructure/persistence/event_store_facade.py:87`
Description: `SqlExecutor.execute()` calls `await self.session.commit()` unconditionally at line 20. `ProjectionExecutor.execute_projections()` calls `self._sql.execute(sql, params)` for every projection. After all projections run, `CleanArchitectureEventStore.save_event()` calls `await session.commit()` again at line 87. This means: (1) every individual projection SQL statement triggers its own immediate `COMMIT`, breaking atomicity — if projection 3 of 7 fails after projections 1 and 2 already committed, those writes are permanent with no rollback; (2) the final `session.commit()` in the facade is a no-op on an already-committed session, which is harmless but indicates the design is confused. The advertised behaviour in REFACTORING_SUMMARY.md ("Statements are parameterized and executed in a transaction") is not what happens in practice.
Recommendation: Remove `await self.session.commit()` from `SqlExecutor.execute()`. The session lifecycle (open → work → commit/rollback → close) must be owned exclusively by `CleanArchitectureEventStore.save_event()` which already wraps everything in `async with self._sessionmaker() as session:` and calls `await session.commit()` at the end. `ProjectionExecutor` should accumulate SQL via `execute()` without committing; the single top-level commit persists everything atomically.

---

## HIGH

---

[HIGH] Application layer directly imports infrastructure concrete classes (Clean Architecture violation)

Services affected: event-saver
Location: `event_saver/application/use_cases/ingest_event.py:11`, `event_saver/application/services/projection_executor.py:8`
Description: `IngestEventUseCase` imports `BookingRepository` and `EventRepository` (concrete infrastructure classes) directly. `ProjectionExecutor` imports `BaseProjection` from `infrastructure/persistence/projections/base.py`. Clean Architecture requires the application layer to depend only on interfaces (Protocols), not on infrastructure implementations. This means changing a repository implementation forces recompilation/review of the use case, and the use case cannot be tested in isolation without a real SQL session.
Recommendation: Define repository protocols in `interfaces/` (e.g., `IEventRepository`, `IBookingRepository`) and have `IngestEventUseCase` depend on those protocols. Similarly, move `BaseProjection` to `interfaces/` or `application/` as an abstract base so `ProjectionExecutor` has no reason to reach into `infrastructure/`. Wire the concrete classes only in `ioc.py`.

---

[HIGH] `booking.rescheduled` event type is not defined in `EventType` enum — a bare string literal is used

Services affected: event-saver
Location: `event_saver/config.py:18`, `event_saver/event_types.py`
Description: `config.py` hardcodes `type_pattern="booking.rescheduled"` as a raw string literal in the default routing rules. Every other event type in the same function uses `EventType.*` enum members. `BOOKING_RESCHEDULED` is missing from `EventType`. This string will silently never match if it ever drifts from the actual event type emitted by `event-receiver`, and it cannot be refactored by IDE tooling. It is also inconsistent with `booking.reminder_sent` which is similarly omitted from the enum but referenced by both a bare string and a duplicate `EventType.BOOKING_REMINDER_SENT` rule (lines 14-20 in config.py define `BOOKING_REMINDER_SENT` → `events.booking.lifecycle` AND `booking.reminder_sent` → `events.booking.reminder`, meaning `reminder_sent` events match the lifecycle rule first and never reach the reminder queue).
Recommendation: Add `BOOKING_RESCHEDULED = "booking.rescheduled"` to the `EventType` enum and replace the string literal in `config.py`. Also audit the duplicate `BOOKING_REMINDER_SENT` routing rules — if `events.booking.reminder` is a real consumer queue it will never receive messages because `events.booking.lifecycle` matches first.

---

[HIGH] No DLQ (dead-letter queue) configured; failed messages are silently lost or cause broker-level infinite redelivery

Services affected: event-saver
Location: `event_saver/adapters/consumer.py:51-68`
Description: `RabbitEventConsumerRunner.start()` declares subscriptions via `self._broker.subscriber()` with no `x-dead-letter-exchange` or `x-dead-letter-routing-key` arguments on the queue. When `_consume_message` raises an exception (lines 87-92 and 127-137 both re-raise), FastStream's default behaviour is to nack the message. Without a DLQ binding, RabbitMQ's behaviour depends on broker configuration: the message is either discarded or requeued indefinitely. There is no exponential back-off, no retry limit, and no dead-letter destination. A single malformed or persistently-failing message can block queue processing or be silently dropped.
Recommendation: Configure a DLQ exchange and routing key when declaring each queue in `RabbitEventConsumerRunner.start()`. Set `x-dead-letter-exchange` and `x-message-ttl` / `x-delivery-limit` arguments on the `RabbitQueue`. Alternatively use FastStream's `no_ack=False` with explicit ack/nack handling and a finite retry strategy before routing to the DLQ.

---

[HIGH] `IEventProjectionStatementFactory` is an orphaned legacy interface — exported publicly but never implemented or used

Services affected: event-saver
Location: `event_saver/interfaces/projection.py:16-29`, `event_saver/interfaces/__init__.py:5,16`
Description: `IEventProjectionStatementFactory` is a Protocol declared in `interfaces/projection.py` and re-exported from `interfaces/__init__.py`. It has a different signature (`build_projection_statements`, `organizer_ref_id: int`) than the current projection system (which uses `BaseProjection.handle` returning a `tuple[str, dict]`). No class in the codebase implements this interface and it is not wired in `ioc.py`. It is a leftover from the old architecture described in REFACTORING_SUMMARY.md. Its presence in the public `__all__` list actively misleads developers about how the projection system works.
Recommendation: Delete `IEventProjectionStatementFactory` from `interfaces/projection.py` and remove it from `interfaces/__init__.py`. Run `grep` to confirm zero usages before deleting.

---

## MEDIUM

---

[MEDIUM] Deduplication hash is computed with `ujson.dumps` (Python-side) but the DB constraint is `md5(payload::text)` (Postgres-side) — these are not equivalent

Services affected: event-saver
Location: `event_saver/domain/services/event_parser.py:82-85`, `event_saver/infrastructure/persistence/repositories/event_repository.py:104` (legacy constraint `ON CONFLICT (booking_id, event_type, source, hash)`)
Description: `EventParser._compute_payload_hash()` computes `md5(ujson.dumps(payload).encode())` in Python and stores the result in the `hash` column. The legacy unique constraint (used when no `idempotency_key` is present) is `ON CONFLICT (booking_id, event_type, source, hash)`. CLAUDE.md describes the hash as `md5(payload::text)`, implying a PostgreSQL text cast. These are different serializations: `ujson` may produce different key ordering or float formatting than PostgreSQL's JSONB `::text` cast. If the hash column was initially populated by a Postgres-generated value (e.g., a migration trigger or earlier code that used `md5(payload::text)`), the Python-generated hash will not match existing rows, silently breaking deduplication for legacy events. The idempotency-key path avoids this entirely, but legacy events without an idempotency key fall back to the broken hash path.
Recommendation: Align the hash function. Either (a) compute the hash consistently in Postgres (use a generated column `hash TEXT GENERATED ALWAYS AS (md5(payload::text)) STORED`) so the application can rely on the DB constraint without computing a hash, or (b) document explicitly that the Python hash replaces the Postgres hash and verify all existing rows' `hash` values were also computed by ujson. Add a test that inserts the same payload twice via the legacy path and asserts exactly one row is stored.

---

[MEDIUM] `ProjectionExecutor` silently swallows projection failures — no propagation, no alerting, no ack/nack signal

Services affected: event-saver
Location: `event_saver/application/services/projection_executor.py:60-66`
Description: Each projection is wrapped in a bare `except Exception: logger.exception(...)` with no re-raise and no counter/metric emission. A projection that fails (e.g., due to a DB constraint or a bug in payload extraction) is logged but the exception is consumed. The raw event is committed as saved, the message is acknowledged, and the projection data is permanently lost with no retry signal. Given there is no DLQ (see HIGH finding above), there is no recovery path.
Recommendation: At a minimum, emit a structured metric or alert when a projection fails (e.g., via structlog with a machine-parseable key `projection_failed=True`). Consider whether a projection failure should nack the message (causing retry) or be accepted as a degraded-mode write. If projections are considered non-critical relative to raw event storage, document this explicitly and add a separate retry/replay mechanism for failed projections.

---

[MEDIUM] `IngestEventUseCase` skips projections entirely when `booking_ref_id` comes back `None` after `get_or_none` returns `None` but `upsert` also somehow fails

Services affected: event-saver
Location: `event_saver/application/use_cases/ingest_event.py:93-127`
Description: The flow is: `get_or_none` → if None → `upsert` → `save_organizer_history` → `execute_projections`. If `booking_repository.upsert()` raises a `RuntimeError` (line 72 of `booking_repository.py`), projections are never executed but the raw event has already been saved (and the `execute()` intermediate commits means some projection SQL may have already been issued). The partial state is not rolled back atomically. This is a consequence of the double-commit issue but also a logic gap: there is no clear handling of the case where the booking cannot be upserted.
Recommendation: Ensure all writes in `save_event` happen in a single database transaction. Once the double-commit issue in `SqlExecutor.execute()` is fixed, a single `session.commit()` at the end of `CleanArchitectureEventStore.save_event()` will make all writes atomic. Add explicit handling (or at least a log+metric) if `upsert` raises.

---

[MEDIUM] `TelegramNotificationProjection.handle()` returns SQL even when `user_id` is `None`

Services affected: event-saver
Location: `event_saver/infrastructure/persistence/projections/notification_projection.py:199`
Description: In `TelegramNotificationProjection.handle()`, `user_id` is resolved as `organizer_user_id if role == ParticipantRole.ORGANIZER else client_user_id`. If `role` is neither ORGANIZER nor CLIENT (e.g., missing or unknown), `user_id` falls back to `client_user_id` which may be `None`. Unlike `EmailNotificationProjection._handle_email_sent()` which guards with an early `None` check on `job_id`, `TelegramNotificationProjection` proceeds to build and return the SQL statement with `user_id=None`. If the `booking_telegram_notifications` table has a NOT NULL constraint on `user_id`, this causes a DB error; if it allows NULL, rows with null `user_id` make the projection data useless.
Recommendation: Add a guard: `if user_id is None: return None` before constructing the SQL in `TelegramNotificationProjection.handle()`, mirroring the pattern in `EmailNotificationProjection`.

---

[MEDIUM] `BookingDataExtractor` only maps two event types to a status (`created`, `cancelled`) — `reassigned`, `rescheduled`, `reminder_sent` produce `status=None`

Services affected: event-saver
Location: `event_saver/domain/services/booking_extractor.py:9-12`
Description: `_STATUS_BY_EVENT_TYPE` only covers `booking.created` → `"created"` and `booking.cancelled` → `"cancelled"`. Events like `booking.events.v1.booking.reassigned.create`, `booking.rescheduled`, and `booking.events.v1.booking.reminder_sent.create` produce `BookingData(status=None)`. When `BookingRepository.upsert()` receives `current_status=None`, the `ON CONFLICT ... DO UPDATE SET current_status = coalesce(excluded.current_status, bookings.current_status)` clause preserves the existing value, so a reassignment event will not flip the status. This is arguably correct for `reassigned` (status does not change) but may be wrong for `rescheduled` (which could warrant a dedicated status) and is certainly confusing.
Recommendation: Document the intentional omissions explicitly in `_STATUS_BY_EVENT_TYPE` with inline comments, or add entries for all expected event types (even if they map to the same existing status). This makes the mapping self-documenting rather than appearing incomplete.

---

[MEDIUM] `adapters/consumer.py` — `declare=False` on subscribed queues means the service will crash if queues don't pre-exist

Services affected: event-saver
Location: `event_saver/adapters/consumer.py:57`
Description: `RabbitQueue(..., declare=False)` means FastStream will not declare the queue if it is absent. Combined with no DLQ configuration (HIGH finding above), there is no defensive setup. If the broker is fresh or a queue is accidentally deleted, the broker will reject the subscription and the consumer will fail silently or crash at startup. There is also no check in `start()` that the queues were successfully bound.
Recommendation: Either set `declare=True` and provide full queue arguments (durable, arguments for DLQ, etc.), or ensure `RabbitTopologyManager` (which is wired in `ioc.py` but not called during startup) explicitly creates queues before `RabbitEventConsumerRunner.start()` is called. Currently `ITopologyManager` is provided by DI but `RabbitEventConsumerRunner` does not receive or call it — verify this is intentional.

---

[MEDIUM] CLAUDE.md references non-existent `domain/models/participant.py` and `infrastructure/persistence/repositories/participant_repository.py`

Services affected: event-saver (documentation)
Location: `event_saver/CLAUDE.md` (architecture diagram), `REFACTORING_SUMMARY.md` (new architecture table)
Description: CLAUDE.md lists `domain/models/participant.py` (with a `Participant` model) and `infrastructure/persistence/repositories/participant_repository.py` in the architecture diagram. Neither file exists in the codebase. `ParticipantExtractor` extracts UUIDs but there is no participant domain model and no participant repository. The `IngestEventUseCase` in `execute()` calls `_process_participants()` which returns UUIDs directly — there is no participant upsert step despite REFACTORING_SUMMARY.md showing `await self._participant_repository.upsert(participants)` in the documented use-case flow.
Recommendation: Update CLAUDE.md and REFACTORING_SUMMARY.md to remove references to `participant.py` and `participant_repository.py`. Document the actual flow: participant UUIDs are extracted from `normalized.participants` and passed directly as `organizer_user_id` / `client_user_id` to the booking repository and projections.

---

## LOW

---

[LOW] `ioc_new.py` is referenced in CLAUDE.md as the canonical DI file but does not exist

Services affected: event-saver (documentation)
Location: `CLAUDE.md:121`, `CLAUDE.md:130`, `CLAUDE.md:258`
Description: CLAUDE.md instructs developers to "Wire in `ioc_new.py`" when adding features, and lists `ioc_new.py` as "New DI container with clean architecture" under Important Files. This file does not exist. The actual DI container is `ioc.py`. Any developer following these instructions will create a new file that is never imported instead of modifying the active container.
Recommendation: Replace all occurrences of `ioc_new.py` in CLAUDE.md with `ioc.py`. Also remove the "Legacy (To be removed)" labels from `ioc.py` and `adapters/event_store.py` since both the refactoring and cleanup are already complete per REFACTORING_SUMMARY.md.

---

[LOW] `adapters/event_store.py` listed as "legacy to remove" in CLAUDE.md — it does not exist and was already deleted

Services affected: event-saver (documentation)
Location: `CLAUDE.md` ("Legacy" section), `REFACTORING_SUMMARY.md` ("Удалены файлы" section)
Description: REFACTORING_SUMMARY.md confirms `adapters/event_store.py` was deleted as part of the clean-architecture migration. CLAUDE.md still lists it as "Legacy (To be removed)". This is stale documentation that creates confusion — the file is gone, there is nothing to delete.
Recommendation: Remove the "Legacy" section from CLAUDE.md or replace it with a note that the refactoring is complete. No code changes needed.

---

[LOW] `SqlExecutor.execute()` is unused in the current projection pipeline but its auto-commit semantics are dangerous

Services affected: event-saver
Location: `event_saver/adapters/sql.py:18-20`
Description: `ProjectionExecutor` calls `self._sql.execute(sql, params)` to persist each projection result. This method commits immediately (see CRITICAL finding). The `execute_in_transaction()` method — which batches statements safely — is declared but not called anywhere in the projection or repository code. This means `execute_in_transaction()` is effectively dead code, and all execution goes through the auto-committing `execute()`.
Recommendation: Once the CRITICAL double-commit issue is fixed (by removing the `session.commit()` from `execute()`), review whether `execute_in_transaction()` should be deprecated or promoted as the preferred method for multi-statement work.

---

[LOW] `EventRouter` and `IEventRouter` are wired and instantiated but never called within event-saver itself

Services affected: event-saver
Location: `event_saver/ioc.py:93-109`, `event_saver/adapters/publisher.py`
Description: `EventRouter` and `CloudEventPublisher` are provided in the DI container (`provide_event_router`, `provide_publisher`) but neither is injected into the consumer or use-case. The publisher appears to exist for potential outbound event forwarding which is not implemented. This adds unused complexity to the container and can confuse developers into thinking event-saver re-publishes events.
Recommendation: If event-saver is not intended to re-publish events, remove `provide_event_router`, `provide_publisher`, `CloudEventPublisher`, and `ICloudEventPublisher` from `ioc.py`. If re-publishing is planned, add a `TODO` comment and ticket reference.

---

[LOW] `_parse_occurred_at` logic is duplicated between `consumer.py` and `domain/services/event_parser.py`

Services affected: event-saver
Location: `event_saver/adapters/consumer.py:21-29`, `event_saver/domain/services/event_parser.py:70-79`
Description: Both `consumer.py` and `EventParser` contain an identical `_parse_occurred_at` function. `consumer.py` parses the timestamp before passing it to `event_store.save_event()`, and `EventParser.parse()` parses it again. The consumer's result is passed as `occurred_at` (a `datetime`) to `save_event`, which passes it as `time` to `IngestEventUseCase.execute()`, which passes it to `EventParser.parse()` as `time`. Since the consumer already ensures it is a timezone-aware `datetime`, the second parse is a no-op but the duplication is a maintenance hazard.
Recommendation: Remove `_parse_occurred_at` from `consumer.py`. Pass `event["time"]` directly (as the raw CloudEvents time value) and let `EventParser` do the single authoritative parse.

---

[LOW] QUEUES_DIGEST.md queue names differ from `config.py` routing destinations

Services affected: event-saver (documentation)
Location: `QUEUES_DIGEST.md`, `event_saver/config.py`
Description: QUEUES_DIGEST.md lists `events.chat.activity` and `events.chat.lifecycle` as separate queues. In `config.py`, `chat.message_sent` events route to `events.chat.activity` and `chat.created`/`chat.deleted` to `events.chat.lifecycle` — these match. However the digest omits `events.chat` (GetStream queue) and `events.mail` (UniSender queue) from the summary table at the top, listing only 8 rows. The actual routing rules in `config.py` define 10 distinct destinations including `events.chat` and `events.mail`. A developer reading only the summary table will miss that GetStream and UniSender events are consumed.
Recommendation: Add `events.chat` (GetStream) and `events.mail` (UniSender) rows to the summary table in QUEUES_DIGEST.md to match all 10 routing destinations in `config.py`.

---

[LOW] No tests exist anywhere in the service

Services affected: event-saver
Location: entire `event_saver/` directory
Description: The REFACTORING_SUMMARY.md explicitly lists "Написать тесты для domain layer" as a next step, but no test directory, test files, or pytest configuration were found in the service. The domain layer (`EventParser`, `ParticipantExtractor`, `BookingDataExtractor`) was designed to be testable without infrastructure, but remains untested. The projection handlers are also untested. Given this is pre-production, the lack of tests is a significant risk ahead of any first deployment.
Recommendation: Create `tests/unit/` for domain and projection handler tests and `tests/integration/` for repository tests against a real PostgreSQL instance (using `pytest-asyncio` + `testcontainers` or a Docker Compose fixture). Priority: `EventParser` hash computation (ties to deduplication correctness), `ProjectionExecutor` exception handling (verifies isolation behaviour), and `EventRepository.save` idempotency.

---

## Summary

| Severity | Count |
|---|---|
| CRITICAL | 2 |
| HIGH | 4 |
| MEDIUM | 6 |
| LOW | 7 |
| **Total** | **19** |

### Key Observations

1. **`ioc.py` is NOT legacy** — it is the live, clean-architecture DI container. `ioc_new.py` was never created. All documentation calling `ioc.py` legacy is incorrect. The refactoring described in REFACTORING_SUMMARY.md has been fully completed; the "legacy" section of CLAUDE.md is stale.

2. **`adapters/event_store.py` is NOT legacy** — it was already deleted as part of the refactoring. No import sites exist. Nothing to remove.

3. **The double-commit in `SqlExecutor.execute()`** is the most impactful active bug: it breaks transactional atomicity across all projection writes.

4. **No tests exist** — the service is well-architected for testability but untested.

---

## Legacy Deletion Plan

Based on the audit, the so-called "legacy" files have already been removed. The items that remain and should be cleaned up are:

1. **`event_saver/interfaces/projection.py`** — Remove `IEventProjectionStatementFactory` (lines 16-29). It is an orphaned legacy Protocol with zero implementations and zero call sites. The file itself can be retained for `IBookingEventClassifier`.

2. **`event_saver/interfaces/__init__.py`** — Remove `IEventProjectionStatementFactory` from the import and `__all__` list (lines 5 and 16).

3. **`CLAUDE.md`** — Remove the "Legacy (To be removed)" section listing `adapters/event_store.py` and `ioc.py`. Replace `ioc_new.py` references on lines 121, 130, and 258 with `ioc.py`.

4. **`REFACTORING_SUMMARY.md`** — The "Удалены файлы" section lists files as deleted with checkmarks; this document can be archived or removed since the refactoring is complete and its "next steps" section suggests unfinished work.

No production code files require deletion. All previously-identified legacy code (`adapters/event_store.py`, the old projections SQL builders, `ioc_old.py`) was already removed prior to this audit.

---

## Resolved Findings

| ID | Finding | Resolution | Date |
|---|---|---|---|
| C-5 | SqlExecutor auto-commit breaks atomicity | Was already fixed: execute() has no commit(), single commit in event_store_facade | 2026-04-21 |
| H-3 | Missing BOOKING_RESCHEDULED in EventType | Was already present in event-schemas types.py | 2026-04-21 |
| H-1 | Application layer imports concrete infrastructure | Replaced with IEventRepository, IBookingRepository, IProjectionHandler protocols | 2026-04-21 |
| H-4 | Orphaned IEventProjectionStatementFactory | Removed along with all dead code (publisher, topology manager, unused interfaces) | 2026-04-21 |
| M-2 | Projection failures silently swallowed | Added re-raise after logging, failures now trigger DLQ | 2026-04-21 |
| M-1 | Deduplication hash mismatch | Replaced ujson.dumps with json.dumps(sort_keys=True) | 2026-04-21 |
| M-4 | TelegramNotificationProjection NULL user_id | Was already fixed: null check at line 189 | 2026-04-21 |
| M-6 | declare=False on queues | Was already changed to declare=True | 2026-04-21 |
| L-1 | ioc_new.py references | No references found in current CLAUDE.md | 2026-04-21 |
| L-3 | execute_in_transaction unused | Removed from SqlExecutor and ISqlExecutor | 2026-04-21 |
| L-4 | EventRouter/CloudEventPublisher wired but unused | Removed publisher.py, routing interfaces, topology manager | 2026-04-21 |
| L-6 | QUEUES_DIGEST.md incomplete | Synced with actual config.py routing rules | 2026-04-21 |
| NEW-1 | All projections (except VideoEventProjection) read payload fields from top level instead of `original` — silently producing NULLs | Fixed: all projections now use `payload.get("original", payload)` pattern | 2026-04-22 |
| NEW-2 | BookingTimelineClassifier reads getstream `type` from wrong payload level | Fixed: `_extract_action_by_source` and `_extract_action_by_queue_chat` now read from `original` | 2026-04-22 |
| NEW-3 | MeetingLinkProjection ignores `meeting.url_deleted` events — deleted links persist in DB | Fixed: added `MEETING_URL_DELETED` handling with DELETE statement | 2026-04-22 |
