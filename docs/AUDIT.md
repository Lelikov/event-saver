# event-saver Audit Findings (audit-v2)

Audited: 2026-06-11 (full re-audit; supersedes the 2026-04-20 report)
Fix branch: `audit-fixes`

All findings of every severity were fixed or explicitly closed. Cross-service
contract items follow `../docs/audit/v2/CONTRACT_DECISIONS.md`.

---

## HIGH — all resolved

### booking.rejected consumed but never reflected — RESOLVED 2026-06-11

`_STATUS_BY_EVENT_TYPE` lacked `BOOKING_REJECTED` and `LifecycleProjection`
omitted it from `_LIFECYCLE_TYPES`/`_ACTION_MAP`, so a rejected booking kept
status `created` and had no timeline row. Fixed: status maps to `rejected`,
lifecycle projection writes action `rejected` with `BookingRejectedPayload`
details (`rejection_type`, `rejection_reasons`, `available_from`,
`has_active_booking`, `active_booking_start`). Commit `f581bdc`.

### No retry path for transient failures — RESOLVED 2026-06-11

Any handler exception rejected the message into the unconsumed 24h-TTL DLQ
(permanent loss during a DB outage). Fixed in `adapters/consumer.py`:
transient errors (DB connectivity, pool/network timeouts) are retried
in-process with exponential backoff (3 attempts) and then NACKed with
`requeue=True`; only poison messages (parse/validation errors) are rejected
to the DLQ. Commit `26df5cb`. DLQ args (24h TTL) stay canonical per
CONTRACT_DECISIONS D2; a DLQ consumer/alerting remains a platform-level TODO.

### No consumer prefetch (QoS) — RESOLVED 2026-06-11

FastStream default channel had unlimited prefetch: a backlog flood exhausted
the DB pool and defeated `x-max-priority`. Fixed: `RabbitRouter` is built with
`default_channel=Channel(prefetch_count=RABBIT_PREFETCH_COUNT)` (default 10,
within pool headroom) and `graceful_timeout=RABBIT_GRACEFUL_TIMEOUT`
(default 30s). Commit `eae3a76`.

---

## MEDIUM — all resolved

### events.dlx / DLQs never declared by event-saver — RESOLVED (contracts wave)

`RabbitEventConsumerRunner._ensure_dead_letter_topology()` idempotently
declares `events.dlx` and the service's own DLQs at startup; queue specs come
from `event_schemas.queues.SAVER_QUEUES`. Commit `f61f098` (contracts wave).

### previous_booking flat-key lookup — RESOLVED (contracts wave)

`BookingRescheduledPayload` now carries top-level `previous_start_time` and
`previous_booking_uid` (cal.com `rescheduleUid`); the lifecycle projection
picks them flat and the test codifies the canonical shape. Commit `f61f098`.

### Alembic ORM models drifted from real schema — RESOLVED 2026-06-11

`db/models.py` now matches the migration chain: `events` gained
`idempotency_key`/`trace_id`/`span_id`/`dataschema` plus the
`idx_events_idempotency` (partial unique) and `idx_events_trace_id` indexes;
`BookingLifecycleEvent` model added. Guard tests in `tests/test_db_models.py`
fail on future drift. Commit `a9f911d`.

### Duplicate BOOKING_REMINDER_SENT rules / stale pseudo-routing table — RESOLVED (contracts wave)

`routing.py`, `EventRouter`, `RoutingConfig` and `Settings.routing` were
deleted; the consumer subscribes to the explicit `SAVER_QUEUES` list from
`event_schemas`. Closes the April H-10 residue. Commit `f61f098`.

### Test coverage gaps (April) — RESOLVED 2026-06-11

Added unit tests for `EventRepository`, `BookingRepository`,
`IngestEventUseCase`, `RabbitEventConsumerRunner` (retry/poison/closure
factory), chat/meeting/video/notification projections, broker construction
and `db/models.py` drift. Suite: 100 tests. Commits `0d10102`..`04a0bf9`.

---

## LOW — all resolved

| Finding | Resolution |
|---|---|
| Dual dedup paths could crash; NULL-key events never deduped | Single `INSERT ... ON CONFLICT DO NOTHING` (suppresses PK + idempotency-key violations); legacy 4-column unique index dropped by migration `a9d4c1f0b7e2`. Commit `ed675bd` |
| Migration-backfilled hash != application hash | Moot: hash is informational only after the legacy dedup index drop (`a9d4c1f0b7e2`) |
| Stale routing config / EventRouter dead code | Deleted in contracts wave (`f61f098`) |
| Dead code: `decode_user_id`, `getstream_user_id_encryption_key`, `QUEUE_DOMAIN_MAP` | Deleted; `cryptography` dependency removed. Commit `b4c9332` |
| ChatReadUpdateProjection never marks NULL user_id rows read | `user_id is distinct from :reader_user_id`. Commit `62a0fb6` |
| Style: elif/else chains, nested ternaries, 27 ruff errors | Ruff clean; guard clauses + `_parse_uuid`/`_user_id_for_role` helpers. Commit `b4c9332` |
| Doc/code drift (participants table, dedup formula, "FastStream handles retry", stale one-off reports) | CLAUDE.md/digests/docs rewritten; stale reports deleted (this commit) |
| No health/readiness endpoint | `GET /health` + `GET /ready` (SELECT 1). Commit `abc7075` |
| `_queue_name` default parameter treated as body field | Closure factory `_make_handler(queue_name)`. Commit `26df5cb` |
| `get_or_none` compared against renamed lifecycle queue (regression risk) | Compares `BOOKING_LIFECYCLE_SAVER_QUEUE.name` from event_schemas. Commit `0d10102` |

---

## Post-audit follow-ups

- **audit-v2 follow-up #9 — user_id backfill/reconciliation (FIXED 2026-06-11):**
  bookings persisted with NULL `organizer_user_id`/`client_user_id` (event-users
  down at ingress) are now reconciled by a periodic background task
  (`UserIdBackfillService` + `UserIdBackfillRunner`, opt-in via
  `USER_ID_BACKFILL_ENABLED`). Emails come from the latest stored event payload;
  identities resolve via event-users `GET /api/users/by-identity`; transport
  errors skip the cycle. See SERVICE_OVERVIEW.md § Background Tasks.

- **Event-driven user_id backfill via `user.synced` (added with event-db-sync):**
  event-saver now consumes `user.synced` on the new saver-owned `events.user.synced`
  queue and backfills `bookings.organizer_user_id` / `bookings.client_user_id` by
  matching the participant email (join through
  `events.payload->'normalized'->'participants'`), NULL-guarded and idempotent. The
  event flows from `event-db-sync` (`user.upserted`, trigger-driven from the cal.com DB)
  → `event-users` (upsert + `user.synced`, both published directly to RabbitMQ). This is
  the fast path; the HTTP-poll `UserIdBackfillService` follow-up #9 above remains as a
  slow safety net. See QUEUES_DIGEST.md § events.user.synced and
  `../../docs/architecture/MESSAGE_CONTRACTS.md`.

---

## Accepted / documented decisions

- **`events.notification.commands` and `events.user.email` are not persisted
  by event-saver.** They are command messages (imperatives), not facts; the
  system of record stores facts. The resulting `notification.*.message_sent`
  facts ARE persisted via `events.notification.delivery`. If a full command
  audit trail is ever needed, add saver-owned queues bound to those routing
  keys (see QUEUES_DIGEST.md).
- **DLQ message TTL (24h) is canonical** per CONTRACT_DECISIONS D2. With the
  transient-retry fix, only poison messages reach the DLQ; alerting/re-shovel
  tooling is tracked at the platform level, not per-service.
