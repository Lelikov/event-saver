"""Domain service for extracting participants from event payloads."""

from typing import Any

from event_saver.domain.models.participant import Participant


class ParticipantExtractor:
    """Extract participant information from normalized event payloads.

    Expects normalized structure from event-receiver:
    {
        "normalized": {
            "participants": [
                {"email": "...", "role": "...", "time_zone": "..."}
            ]
        }
    }

    All normalization (including GetStream user ID decoding) is done by event-receiver.
    """

    def extract(self, payload: dict[str, Any]) -> list[Participant]:
        """Extract participants from normalized payload."""
        normalized = payload.get("normalized")
        if not isinstance(normalized, dict):
            return []

        participants_data = normalized.get("participants", [])
        if not isinstance(participants_data, list):
            return []

        participants: list[Participant] = []

        for p in participants_data:
            if not isinstance(p, dict):
                continue

            email = p.get("email")
            if not isinstance(email, str) or not email:
                continue

            participants.append(
                Participant(
                    email=email,
                    role=p.get("role") if isinstance(p.get("role"), str) else None,
                    time_zone=p.get("time_zone") if isinstance(p.get("time_zone"), str) else None,
                )
            )

        return participants
