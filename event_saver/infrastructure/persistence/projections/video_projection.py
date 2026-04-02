"""Projection for video conference events."""

from datetime import UTC, datetime
from typing import Any

import ujson

from event_saver.domain.models.event import ParsedEvent
from event_saver.event_types import SourceType
from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.interfaces.projection import IBookingEventClassifier


class VideoEventProjection(BaseProjection):
    """Projects video conference events to booking_video_events table.

    Handles: Jitsi events (source: jitsi)
    """

    def __init__(self, classifier: IBookingEventClassifier) -> None:
        self._classifier = classifier

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type.startswith("jitsi.events.v1.")

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        video_event_type = self._classifier.extract_action(
            queue_name=queue_name,
            event_type=event.event_type,
            source=SourceType.JITSI,
            payload=event.payload,
        )

        participant_role = self._extract_participant_role(event.payload)
        participant_ref_id = self._resolve_participant_ref_id(
            participant_role,
            organizer_ref_id,
            client_ref_id,
        )

        event_time = self._extract_event_time(event.payload)
        projected_payload = self._project_payload(video_event_type, event.payload)

        return (
            """
            insert into booking_video_events (
                booking_ref_id,
                raw_event_id,
                video_event_type,
                participant_role,
                participant_ref_id,
                event_time,
                payload
            ) values (
                :booking_ref_id,
                :raw_event_id,
                :video_event_type,
                :participant_role,
                :participant_ref_id,
                :event_time,
                cast(:payload as jsonb)
            )
            on conflict (raw_event_id) do nothing
            """,
            {
                "booking_ref_id": booking_ref_id,
                "raw_event_id": event.event_id,
                "video_event_type": video_event_type,
                "participant_role": participant_role,
                "participant_ref_id": participant_ref_id,
                "event_time": event_time,
                "payload": ujson.dumps(projected_payload),
            },
        )

    @staticmethod
    def _extract_participant_role(payload: dict[str, Any]) -> str | None:
        """Extract participant role from context.user.role."""
        context = payload.get("context")
        if not isinstance(context, dict):
            return None

        user = context.get("user")
        if not isinstance(user, dict):
            return None

        role = user.get("role")
        return role if isinstance(role, str) else None

    @staticmethod
    def _resolve_participant_ref_id(
        role: str | None,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
    ) -> int | None:
        """Map role to participant ref ID."""
        if role == "organizer":
            return organizer_ref_id
        if role == "client":
            return client_ref_id
        return None

    @staticmethod
    def _extract_event_time(payload: dict[str, Any]) -> datetime | None:
        """Parse event time from payload."""
        time_value = payload.get("time")
        if isinstance(time_value, datetime):
            return time_value
        if not isinstance(time_value, str) or not time_value:
            return None

        candidate = time_value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None

    @staticmethod
    def _project_payload(video_event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Project payload to only relevant fields for each event type.

        Reduces storage by filtering out irrelevant data.
        """
        if video_event_type in {"audioMuteStatusChanged", "videoMuteStatusChanged"}:
            muted = payload.get("muted")
            return {"muted": muted} if isinstance(muted, bool) else {}

        if video_event_type == "deviceListChanged":
            devices = payload.get("devices")
            return {"devices": devices} if isinstance(devices, dict) else {}

        if video_event_type in {"videoConferenceJoined", "videoConferenceLeft"}:
            return {}

        return payload
