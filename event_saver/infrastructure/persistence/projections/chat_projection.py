"""Projection for chat events."""

import uuid
from typing import Any

from event_schemas.types import EventType, RecipientRole, SourceType

from event_saver.domain.models.event import ParsedEvent
from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.interfaces.projection import IBookingEventClassifier


_BOOKING_CHAT_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EventType.CHAT_CREATED,
        EventType.CHAT_DELETED,
        EventType.CHAT_MESSAGE_SENT,
    }
)


class ChatEventProjection(BaseProjection):
    """Projects chat events to booking_chat_events table."""

    def __init__(self, classifier: IBookingEventClassifier) -> None:
        self._classifier = classifier

    def can_handle(self, event: ParsedEvent) -> bool:
        if event.source == SourceType.GETSTREAM:
            return True
        if event.source == SourceType.BOOKING:
            return event.event_type in _BOOKING_CHAT_EVENT_TYPES
        return False

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        chat_event_type = self._classifier.extract_action(
            queue_name=queue_name,
            event_type=event.event_type,
            source=event.source,
            payload=event.payload,
        )

        message_id = self._extract_message_id(event.payload)
        user_id = self._extract_participant_user_id(event.payload, organizer_user_id, client_user_id)
        text_preview = self._extract_text_preview(event.payload)

        return (
            """
            insert into booking_chat_events (
                booking_ref_id,
                raw_event_id,
                provider,
                chat_event_type,
                message_id,
                user_id,
                is_read,
                text_preview,
                occurred_at
            ) values (
                :booking_ref_id,
                :raw_event_id,
                :provider,
                :chat_event_type,
                :message_id,
                :user_id,
                :is_read,
                :text_preview,
                :occurred_at
            )
            on conflict (raw_event_id) do nothing
            """,
            {
                "booking_ref_id": booking_ref_id,
                "raw_event_id": event.event_id,
                "provider": event.source,
                "chat_event_type": chat_event_type,
                "message_id": message_id,
                "user_id": str(user_id) if user_id is not None else None,
                "is_read": None,
                "text_preview": text_preview,
                "occurred_at": event.occurred_at,
            },
        )

    @staticmethod
    def _extract_message_id(payload: dict[str, Any]) -> str | None:
        original = payload.get("original", payload)
        message_id = original.get("message_id")
        if isinstance(message_id, str):
            return message_id
        message = original.get("message")
        if isinstance(message, dict):
            msg_id = message.get("id")
            if isinstance(msg_id, str):
                return msg_id
        return None

    @staticmethod
    def _extract_participant_user_id(
        payload: dict[str, Any],
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
        normalized = payload.get("normalized")
        if not isinstance(normalized, dict):
            return None
        participants = normalized.get("participants", [])
        if not isinstance(participants, list) or not participants:
            return None
        first = participants[0]
        if not isinstance(first, dict):
            return None
        role = first.get("role")
        if role == RecipientRole.ORGANIZER:
            return organizer_user_id
        if role == RecipientRole.CLIENT:
            return client_user_id
        return None

    @staticmethod
    def _extract_text_preview(payload: dict[str, Any]) -> str | None:
        original = payload.get("original", payload)
        message = original.get("message")
        if not isinstance(message, dict):
            return None
        text = message.get("text")
        if isinstance(text, str):
            return text[:512]
        return None


class ChatReadUpdateProjection(BaseProjection):
    """Updates chat messages as read based on read events."""

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.source == SourceType.GETSTREAM and event.event_type == EventType.GETSTREAM_MESSAGE_READ

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        reader_user_id = self._extract_reader_user_id(event.payload, organizer_user_id, client_user_id)
        if reader_user_id is None:
            return None

        return (
            """
            update booking_chat_events
            set is_read = true, updated_at = now()
            where booking_ref_id = :booking_ref_id
              and chat_event_type = 'message.new'
              and user_id != :reader_user_id
              and (
                  message_id = :last_read_message_id
                  or occurred_at < :read_occurred_at
              )
            """,
            {
                "booking_ref_id": booking_ref_id,
                "reader_user_id": str(reader_user_id),
                "last_read_message_id": event.payload.get("original", event.payload).get("last_read_message_id"),
                "read_occurred_at": event.occurred_at,
            },
        )

    @staticmethod
    def _extract_reader_user_id(
        payload: dict[str, Any],
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
        normalized = payload.get("normalized")
        if not isinstance(normalized, dict):
            return None
        participants = normalized.get("participants", [])
        if not isinstance(participants, list) or not participants:
            return None
        first = participants[0]
        if not isinstance(first, dict):
            return None
        role = first.get("role")
        if role == RecipientRole.ORGANIZER:
            return organizer_user_id
        if role == RecipientRole.CLIENT:
            return client_user_id
        return None
