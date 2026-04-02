"""Projection for chat events."""

from collections.abc import Callable
from typing import Any

from event_saver.domain.models.event import ParsedEvent
from event_saver.event_types import EventType, ParticipantRole, SourceType
from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.interfaces.projection import IBookingEventClassifier


class ChatEventProjection(BaseProjection):
    """Projects chat events to booking_chat_events table.

    Handles:
    - Booking chat events (source: booking)
    - GetStream chat events (source: getstream)
    """

    def __init__(
        self,
        classifier: IBookingEventClassifier,
        decode_user_id: Callable[[str], str],
    ) -> None:
        self._classifier = classifier
        self._decode_user_id = decode_user_id

    def can_handle(self, event: ParsedEvent) -> bool:
        if event.source not in {SourceType.BOOKING, SourceType.GETSTREAM}:
            return False

        # GetStream events are always chat
        if event.source == SourceType.GETSTREAM:
            return True

        # Booking events must have .chat. in type
        return ".chat." in event.event_type

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        chat_event_type = self._classifier.extract_action(
            queue_name=queue_name,
            event_type=event.event_type,
            source=event.source,
            payload=event.payload,
        )

        message_id = self._extract_message_id(event.payload)
        participant_email = self._extract_participant_email(event)
        participant_ref_id = self._extract_participant_ref_id(
            event.payload,
            organizer_ref_id,
            client_ref_id,
        )
        text_preview = self._extract_text_preview(event.payload)

        return (
            """
            insert into booking_chat_events (
                booking_ref_id,
                raw_event_id,
                provider,
                chat_event_type,
                message_id,
                participant_ref_id,
                is_read,
                text_preview,
                occurred_at
            ) values (
                :booking_ref_id,
                :raw_event_id,
                :provider,
                :chat_event_type,
                :message_id,
                coalesce(:participant_ref_id, (select id from participants where email = :participant_email)),
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
                "participant_ref_id": participant_ref_id,
                "participant_email": participant_email,
                "is_read": None,
                "text_preview": text_preview,
                "occurred_at": event.occurred_at,
            },
        )

    @staticmethod
    def _extract_message_id(payload: dict[str, Any]) -> str | None:
        """Extract message ID from payload."""
        message_id = payload.get("message_id")
        if isinstance(message_id, str):
            return message_id

        message = payload.get("message")
        if isinstance(message, dict):
            msg_id = message.get("id")
            if isinstance(msg_id, str):
                return msg_id

        return None

    def _extract_participant_email(self, event: ParsedEvent) -> str | None:
        """Extract participant email from payload."""
        payload = event.payload

        # Check users array first
        users = payload.get("users")
        if isinstance(users, list) and users:
            first_user = users[0]
            if isinstance(first_user, dict):
                email = first_user.get("email")
                if isinstance(email, str) and email:
                    return email

        # Check user_id
        user_id = payload.get("user_id")
        if isinstance(user_id, str) and "@" in user_id:
            return user_id

        # Check user object
        user = payload.get("user")
        if isinstance(user, dict):
            raw_id = user.get("id")
            if isinstance(raw_id, str) and raw_id:
                if event.source == SourceType.GETSTREAM:
                    decoded = self._decode_user_id(raw_id)
                    return decoded if isinstance(decoded, str) and "@" in decoded else None
                return raw_id if "@" in raw_id else None

        return None

    @staticmethod
    def _extract_participant_ref_id(
        payload: dict[str, Any],
        organizer_ref_id: int | None,
        client_ref_id: int | None,
    ) -> int | None:
        """Extract participant ref ID from users array."""
        users = payload.get("users")
        if not isinstance(users, list) or not users:
            return None

        first_user = users[0]
        if not isinstance(first_user, dict):
            return None

        role = first_user.get("role")
        if role == ParticipantRole.ORGANIZER:
            return organizer_ref_id
        if role == ParticipantRole.CLIENT:
            return client_ref_id

        return None

    @staticmethod
    def _extract_text_preview(payload: dict[str, Any]) -> str | None:
        """Extract text preview from message."""
        message = payload.get("message")
        if not isinstance(message, dict):
            return None

        text = message.get("text")
        if isinstance(text, str):
            return text[:512]

        return None


class ChatReadUpdateProjection(BaseProjection):
    """Updates chat messages as read based on read events.

    Handles: getstream.events.v1.message.read.create
    """

    def __init__(self, decode_user_id: Callable[[str], str]) -> None:
        self._decode_user_id = decode_user_id

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.source == SourceType.GETSTREAM and event.event_type == EventType.GETSTREAM_MESSAGE_READ

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        participant_email = self._extract_participant_email(event)

        return (
            """
            update booking_chat_events
            set is_read = true, updated_at = now()
            where booking_ref_id = :booking_ref_id
              and chat_event_type = 'message.new'
              and participant_ref_id != (select id from participants where email = :participant_email limit 1)
              and (
                  message_id = :last_read_message_id
                  or occurred_at < :read_occurred_at
              )
            """,
            {
                "booking_ref_id": booking_ref_id,
                "participant_email": participant_email,
                "last_read_message_id": event.payload.get("last_read_message_id"),
                "read_occurred_at": event.occurred_at,
            },
        )

    def _extract_participant_email(self, event: ParsedEvent) -> str | None:
        """Extract participant email from payload."""
        payload = event.payload

        # Check users array
        users = payload.get("users")
        if isinstance(users, list) and users:
            first_user = users[0]
            if isinstance(first_user, dict):
                email = first_user.get("email")
                if isinstance(email, str) and email:
                    return email

        # Check user_id
        user_id = payload.get("user_id")
        if isinstance(user_id, str) and "@" in user_id:
            return user_id

        # Check user object with decoding
        user = payload.get("user")
        if isinstance(user, dict):
            raw_id = user.get("id")
            if isinstance(raw_id, str) and raw_id:
                decoded = self._decode_user_id(raw_id)
                return decoded if isinstance(decoded, str) and "@" in decoded else None

        return None
