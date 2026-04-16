"""Projection for video conference events."""

import uuid
from datetime import UTC, datetime
from typing import Any

import ujson

from event_saver.domain.models.event import ParsedEvent
from event_saver.event_types import SourceType
from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.interfaces.projection import IBookingEventClassifier


class VideoEventProjection(BaseProjection):
    """Projects video conference events to booking_video_events table."""

    def __init__(self, classifier: IBookingEventClassifier) -> None:
        self._classifier = classifier

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type.startswith("jitsi.events.v1.")

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        video_event_type = self._classifier.extract_action(
            queue_name=queue_name,
            event_type=event.event_type,
            source=SourceType.JITSI,
            payload=event.payload,
        )

        participant_role = self._extract_participant_role(event.payload)
        user_id = self._resolve_participant_user_id(participant_role, organizer_user_id, client_user_id)

        event_time = self._extract_event_time(event.payload)
        projected_payload = self._project_payload(video_event_type, event.payload)

        return (
            """
            insert into booking_video_events (
                booking_ref_id,
                raw_event_id,
                video_event_type,
                participant_role,
                user_id,
                event_time,
                payload
            ) values (
                :booking_ref_id,
                :raw_event_id,
                :video_event_type,
                :participant_role,
                :user_id,
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
                "user_id": str(user_id) if user_id is not None else None,
                "event_time": event_time,
                "payload": ujson.dumps(projected_payload),
            },
        )

    @staticmethod
    def _extract_participant_role(payload: dict[str, Any]) -> str | None:
        context = payload.get("context")
        if not isinstance(context, dict):
            return None
        user = context.get("user")
        if not isinstance(user, dict):
            return None
        role = user.get("role")
        return role if isinstance(role, str) else None

    @staticmethod
    def _resolve_participant_user_id(
        role: str | None,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
        if role == "organizer":
            return organizer_user_id
        if role == "client":
            return client_user_id
        return None

    @staticmethod
    def _extract_event_time(payload: dict[str, Any]) -> datetime | None:
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
        if video_event_type in {"audioMuteStatusChanged", "videoMuteStatusChanged"}:
            muted = payload.get("muted")
            return {"muted": muted} if isinstance(muted, bool) else {}
        if video_event_type == "deviceListChanged":
            devices = payload.get("devices")
            return {"devices": devices} if isinstance(devices, dict) else {}
        if video_event_type in {"videoConferenceJoined", "videoConferenceLeft"}:
            return {}
        return payload
