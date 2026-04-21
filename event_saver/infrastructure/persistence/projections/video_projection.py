"""Projection for video conference events."""

import uuid
from datetime import datetime
from typing import Any

import ujson
from event_schemas.types import EventType, RecipientRole, SourceType

from event_saver.domain.models.event import ParsedEvent
from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.interfaces.projection import IBookingEventClassifier
from event_saver.utils import parse_iso_datetime


_JITSI_PREFIX = "jitsi."

_JITSI_EVENT_TYPES: frozenset[str] = frozenset(et.value for et in EventType if et.value.startswith(_JITSI_PREFIX))

_MUTE_ACTIONS: frozenset[str] = frozenset(
    {
        EventType.JITSI_AUDIO_MUTE_STATUS_CHANGED.removeprefix(_JITSI_PREFIX),
        EventType.JITSI_VIDEO_MUTE_STATUS_CHANGED.removeprefix(_JITSI_PREFIX),
    }
)

_DEVICE_ACTION: str = EventType.JITSI_DEVICE_LIST_CHANGED.removeprefix(_JITSI_PREFIX)

_CONFERENCE_ACTIONS: frozenset[str] = frozenset(
    {
        EventType.JITSI_CONFERENCE_JOINED.removeprefix(_JITSI_PREFIX),
        EventType.JITSI_CONFERENCE_LEFT.removeprefix(_JITSI_PREFIX),
    }
)


class VideoEventProjection(BaseProjection):
    """Projects video conference events to booking_video_events table."""

    def __init__(self, classifier: IBookingEventClassifier) -> None:
        self._classifier = classifier

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type in _JITSI_EVENT_TYPES

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
        original = payload.get("original", payload)
        context = original.get("context")
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
        if role == RecipientRole.ORGANIZER:
            return organizer_user_id
        if role == RecipientRole.CLIENT:
            return client_user_id
        return None

    @staticmethod
    def _extract_event_time(payload: dict[str, Any]) -> datetime | None:
        original = payload.get("original", payload)
        return parse_iso_datetime(original.get("time"))

    @staticmethod
    def _project_payload(video_event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        original = payload.get("original", payload)
        if video_event_type in _MUTE_ACTIONS:
            muted = original.get("muted")
            return {"muted": muted} if isinstance(muted, bool) else {}
        if video_event_type == _DEVICE_ACTION:
            devices = original.get("devices")
            return {"devices": devices} if isinstance(devices, dict) else {}
        if video_event_type in _CONFERENCE_ACTIONS:
            return {}
        return original
