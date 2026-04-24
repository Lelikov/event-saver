# event-saver Audit Findings

Audited: 2026-04-20

---

## HIGH

---

[HIGH] `booking.rescheduled` event type is not defined in `EventType` enum — a bare string literal is used

Services affected: event-saver
Location: `event_saver/config.py:18`, `event_saver/event_types.py`
Description: `config.py` hardcodes `type_pattern="booking.rescheduled"` as a raw string literal in the default routing rules. Every other event type in the same function uses `EventType.*` enum members. `BOOKING_RESCHEDULED` is missing from `EventType`. This string will silently never match if it ever drifts from the actual event type emitted by `event-receiver`, and it cannot be refactored by IDE tooling. It is also inconsistent with `booking.reminder_sent` which is similarly omitted from the enum but referenced by both a bare string and a duplicate `EventType.BOOKING_REMINDER_SENT` rule (lines 14-20 in config.py define `BOOKING_REMINDER_SENT` → `events.booking.lifecycle` AND `booking.reminder_sent` → `events.booking.reminder`, meaning `reminder_sent` events match the lifecycle rule first and never reach the reminder queue).
Recommendation: Add `BOOKING_RESCHEDULED = "booking.rescheduled"` to the `EventType` enum and replace the string literal in `config.py`. Also audit the duplicate `BOOKING_REMINDER_SENT` routing rules — if `events.booking.reminder` is a real consumer queue it will never receive messages because `events.booking.lifecycle` matches first.

---

## MEDIUM

---

[MEDIUM] `BookingDataExtractor` only maps two event types to a status (`created`, `cancelled`) — `reassigned`, `rescheduled`, `reminder_sent` produce `status=None`

Services affected: event-saver
Location: `event_saver/domain/services/booking_extractor.py:9-12`
Description: `_STATUS_BY_EVENT_TYPE` only covers `booking.created` → `"created"` and `booking.cancelled` → `"cancelled"`. Events like `booking.events.v1.booking.reassigned.create`, `booking.rescheduled`, and `booking.events.v1.booking.reminder_sent.create` produce `BookingData(status=None)`. When `BookingRepository.upsert()` receives `current_status=None`, the `ON CONFLICT ... DO UPDATE SET current_status = coalesce(excluded.current_status, bookings.current_status)` clause preserves the existing value, so a reassignment event will not flip the status. This is arguably correct for `reassigned` (status does not change) but may be wrong for `rescheduled` (which could warrant a dedicated status) and is certainly confusing.
Recommendation: Document the intentional omissions explicitly in `_STATUS_BY_EVENT_TYPE` with inline comments, or add entries for all expected event types (even if they map to the same existing status). This makes the mapping self-documenting rather than appearing incomplete.

---

[MEDIUM] `IngestEventUseCase` skips projections entirely when `booking_ref_id` comes back `None` after `get_or_none` returns `None` but `upsert` also somehow fails

Services affected: event-saver
Location: `event_saver/application/use_cases/ingest_event.py:93-127`
Description: If `booking_repository.upsert()` raises a `RuntimeError`, projections are never executed but the raw event has already been saved. The partial state is not rolled back atomically. There is no clear handling of the case where the booking cannot be upserted.
Recommendation: Add explicit handling (or at least a log+metric) if `upsert` raises. Ensure the session lifecycle guarantees atomic rollback on failure.

---

## LOW

---

[LOW] `_parse_occurred_at` logic is duplicated between `consumer.py` and `domain/services/event_parser.py`

Services affected: event-saver
Location: `event_saver/adapters/consumer.py:21-29`, `event_saver/domain/services/event_parser.py:70-79`
Description: Both `consumer.py` and `EventParser` contain an identical `_parse_occurred_at` function. `consumer.py` parses the timestamp before passing it to `event_store.save_event()`, and `EventParser.parse()` parses it again. Since the consumer already ensures it is a timezone-aware `datetime`, the second parse is a no-op but the duplication is a maintenance hazard.
Recommendation: Remove `_parse_occurred_at` from `consumer.py`. Pass `event["time"]` directly (as the raw CloudEvents time value) and let `EventParser` do the single authoritative parse.

---

[LOW] No tests exist anywhere in the service

Services affected: event-saver
Location: entire `event_saver/` directory
Description: No test directory, test files, or pytest configuration were found in the service. The domain layer (`EventParser`, `ParticipantExtractor`, `BookingDataExtractor`) was designed to be testable without infrastructure, but remains untested. The projection handlers are also untested. Given this is pre-production, the lack of tests is a significant risk ahead of any first deployment.
Recommendation: Create `tests/unit/` for domain and projection handler tests and `tests/integration/` for repository tests against a real PostgreSQL instance (using `pytest-asyncio` + `testcontainers` or a Docker Compose fixture). Priority: `EventParser` hash computation (ties to deduplication correctness), `ProjectionExecutor` exception handling (verifies isolation behaviour), and `EventRepository.save` idempotency.

---

## Summary

| Severity | Count |
|---|---|
| HIGH | 1 |
| MEDIUM | 2 |
| LOW | 2 |
| **Total** | **5** |

### Key Observations

1. **No tests exist** — the service is well-architected for testability but untested.

2. **`BookingDataExtractor` status mapping** is intentionally incomplete by design (COALESCE preserves existing status), but the omissions should be documented inline.

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
