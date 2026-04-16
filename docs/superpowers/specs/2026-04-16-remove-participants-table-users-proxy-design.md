# Design: Remove participants table & add users proxy endpoint

**Date:** 2026-04-16
**Status:** Approved

## Summary

Stop storing full user information (email, role, timezone) in the `participants` table.
Instead, store only `user_id` (UUID) directly on the tables that need it.
Add a `UsersClient` adapter and a proxy endpoint so the frontend can fetch user details
from the upstream users service via event-saver.

The upstream users service already enriches every message with `user_id` before publishing
to RabbitMQ (see `event-receiver/publisher.py` — `participant["user_id"] = await self._user_resolver.resolve_or_create(...)`).
event-saver only needs to read that UUID; it never needs to resolve or store email/timezone.

---

## Section 1: Database

### Drop `participants` table

The `participants` table (`id`, `user_id`, `email`, `role`, `time_zone`, …) is removed entirely.

### Replace all `participant_ref_id` FK columns with `user_id UUID`

| Table | Old column | New column | Nullable |
|---|---|---|---|
| `bookings` | `current_organizer_participant_ref_id BIGINT FK` | `organizer_user_id UUID` | yes |
| `bookings` | `current_client_participant_ref_id BIGINT FK` | `client_user_id UUID` | yes |
| `booking_organizer_history` | `organizer_participant_ref_id BIGINT FK NOT NULL` | `organizer_user_id UUID NOT NULL` |  no |
| `booking_meeting_links` | `participant_ref_id BIGINT FK NOT NULL` | `user_id UUID` | yes |
| `booking_email_notifications` | `participant_ref_id BIGINT FK` | `user_id UUID` | yes |
| `booking_telegram_notifications` | `participant_ref_id BIGINT FK` | `user_id UUID` | yes |
| `booking_chat_events` | `participant_ref_id BIGINT FK` | `user_id UUID` | yes |
| `booking_video_events` | `participant_ref_id BIGINT FK` | `user_id UUID` | yes |

No FK constraint on the new UUID columns — the users service is the authority.

### Migration

Single Alembic migration:
1. Drop all FK constraints referencing `participants.id`.
2. Drop `participant_ref_id` / `current_*_participant_ref_id` columns.
3. Add `user_id UUID` / `organizer_user_id UUID` / `client_user_id UUID` columns.
4. Drop `participants` table.

---

## Section 2: Domain & Application Layer

### `Participant` value object (simplified)

Kept as a thin transient model — only used during event processing to carry user_id → role mapping.
Never persisted.

```python
@dataclass(frozen=True, slots=True)
class Participant:
    user_id: uuid.UUID
    role: str  # "organizer" | "client"
```

### `ParticipantExtractor` (simplified)

Reads `payload["normalized"]["participants"]`, extracts `user_id` + `role`.
Skips entries missing `user_id`. Returns `list[Participant]`.

### `ParticipantRepository` — deleted

No longer needed. No DB table, no repository.

### `IngestEventUseCase._process_participants`

Returns `(organizer_user_id: uuid.UUID | None, client_user_id: uuid.UUID | None)` directly.
No DB calls for participants.

```python
async def _process_participants(self, event) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    participants = self._participant_extractor.extract(event.payload)
    organizer_user_id = next((p.user_id for p in participants if p.role == "organizer"), None)
    client_user_id = next((p.user_id for p in participants if p.role == "client"), None)
    return organizer_user_id, client_user_id
```

### `BookingRepository`

Signatures updated: `organizer_id: int | None` → `organizer_user_id: uuid.UUID | None`,
`client_id: int | None` → `client_user_id: uuid.UUID | None`.

### Projections

All projections that accepted `organizer_id: int | None` / `client_id: int | None` /
`participant_ref_id: int | None` are updated to accept `uuid.UUID | None` instead.

---

## Section 3: Infrastructure — UsersClient + Proxy Endpoint

### Interface

`event_saver/interfaces/users.py`:

```python
from typing import Protocol
import uuid

class IUsersClient(Protocol):
    async def get_user(self, user_id: uuid.UUID) -> dict: ...
```

### `UsersClient` adapter

`event_saver/adapters/users_client.py`:

```python
class UsersClient:
    def __init__(self, *, http_client: AsyncClient, api_token: str) -> None: ...

    async def get_user(self, user_id: uuid.UUID) -> dict:
        response = await self._client.get(
            f"/api/users/{user_id}",
            headers={"Authorization": f"Bearer {self._api_token}"},
        )
        response.raise_for_status()
        return response.json()
```

HTTP errors (404, 403, etc.) propagate as `httpx.HTTPStatusError` and are mapped to
appropriate FastAPI HTTP responses in the endpoint.

### Config

Two new fields in `Settings`:

```python
users_service_url: AnyHttpUrl
users_service_api_token: str
```

### FastAPI proxy endpoint

Registered in `main.py` (or a dedicated `api/users.py` router):

```python
@app.get("/api/users/{user_id}")
async def proxy_get_user(
    user_id: uuid.UUID,
    client: FromDishka[IUsersClient],
) -> dict:
    try:
        return await client.get_user(user_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code) from exc
```

### IoC wiring

- `httpx.AsyncClient` — `Scope.APP`, base_url = `settings.users_service_url`
- `IUsersClient` / `UsersClient` — `Scope.APP`
- `ParticipantRepository` provider — removed
- `getstream_user_id_decoder` provider — removed (no longer needed in event-saver)

---

## Out of scope

- Caching user details in event-saver — can be added later if needed.
- Batch user lookup endpoint — deferred, single `GET /api/users/{user_id}` is sufficient.
- Backfilling historical data — existing rows with NULL user_id columns are acceptable.
