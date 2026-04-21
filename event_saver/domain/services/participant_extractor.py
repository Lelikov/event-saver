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

        organizer_user_id: uuid.UUID | None = None
        client_user_id: uuid.UUID | None = None

        for p in participants_data:
            if not isinstance(p, dict):
                continue

            role = p.get("role")
            raw_user_id = p.get("user_id")

            user_id: uuid.UUID | None = None
            if isinstance(raw_user_id, str):
                try:
                    user_id = uuid.UUID(raw_user_id)
                except ValueError:
                    continue
            elif isinstance(raw_user_id, uuid.UUID):
                user_id = raw_user_id
            else:
                continue

            if role == RecipientRole.ORGANIZER:
                organizer_user_id = user_id
            elif role == RecipientRole.CLIENT:
                client_user_id = user_id

        return organizer_user_id, client_user_id
