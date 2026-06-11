"""Domain service for extracting participant UUIDs from event payloads."""

import uuid
from typing import Any

from event_schemas.types import RecipientRole


class ParticipantExtractor:
    """Extract organizer and client UUIDs from normalized event payloads.

    Expects normalized structure from event-receiver:
    {
        "normalized": {
            "participants": [
                {"role": "organizer", "user_id": "<uuid>"},
                {"role": "client", "user_id": "<uuid>"}
            ]
        }
    }

    role is used only as a routing key — it is never stored or returned.
    """

    def extract(self, payload: dict[str, Any]) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        """Return (organizer_user_id, client_user_id) from normalized payload."""
        normalized = payload.get("normalized")
        if not isinstance(normalized, dict):
            return None, None

        participants_data = normalized.get("participants", [])
        if not isinstance(participants_data, list):
            return None, None

        user_id_by_role: dict[str, uuid.UUID] = {}

        for p in participants_data:
            if not isinstance(p, dict):
                continue

            role = p.get("role")
            if role not in (RecipientRole.ORGANIZER, RecipientRole.CLIENT):
                continue

            user_id = _parse_uuid(p.get("user_id"))
            if user_id is None:
                continue

            user_id_by_role[role] = user_id

        return user_id_by_role.get(RecipientRole.ORGANIZER), user_id_by_role.get(RecipientRole.CLIENT)


def _parse_uuid(raw: Any) -> uuid.UUID | None:
    """Parse a UUID from str or UUID input; return None for anything else."""
    if isinstance(raw, uuid.UUID):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None
