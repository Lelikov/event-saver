"""Projections for notifications (email and telegram)."""

from datetime import UTC, datetime
from typing import Any

from event_saver.domain.models.event import ParsedEvent
from event_saver.event_types import EventType, ParticipantRole
from event_saver.infrastructure.persistence.projections.base import BaseProjection


class EmailNotificationProjection(BaseProjection):
    """Projects email notification events to booking_email_notifications table.

    Handles:
    - booking.events.v1.notification.email.message_sent.create (sent)
    - unisender.events.v1.transactional.status.create (delivery status)
    """

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type in {
            EventType.BOOKING_NOTIFICATION_EMAIL_MESSAGE_SENT,
            EventType.UNISENDER_TRANSACTIONAL_STATUS,
        }

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        if event.event_type == EventType.BOOKING_NOTIFICATION_EMAIL_MESSAGE_SENT:
            return self._handle_email_sent(
                event=event,
                booking_ref_id=booking_ref_id,
                organizer_ref_id=organizer_ref_id,
                client_ref_id=client_ref_id,
            )

        if event.event_type == EventType.UNISENDER_TRANSACTIONAL_STATUS:
            return self._handle_email_status(
                event=event,
                booking_ref_id=booking_ref_id,
            )

        return None

    def _handle_email_sent(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
    ) -> tuple[str, dict[str, Any]] | None:
        """Handle email.message_sent events."""
        job_id = event.payload.get("job_id")
        if not isinstance(job_id, str):
            return None

        users = event.payload.get("users")
        role = users[0].get("role") if isinstance(users, list) and users else None
        trigger_event = event.payload.get("trigger_event")

        email = self._resolve_recipient_email(event.payload, role)

        participant_ref_id = (
            organizer_ref_id
            if role == ParticipantRole.ORGANIZER
            else client_ref_id
            if role == ParticipantRole.CLIENT
            else None
        )

        return (
            """
            insert into booking_email_notifications (
                booking_ref_id,
                participant_ref_id,
                trigger_event,
                job_id,
                sent_event_id,
                sent_at,
                updated_at
            ) values (
                :booking_ref_id,
                coalesce(:participant_ref_id, (select id from participants where email = :email)),
                :trigger_event,
                :job_id,
                :sent_event_id,
                :sent_at,
                now()
            )
            on conflict (job_id) do update
            set
                booking_ref_id = excluded.booking_ref_id,
                participant_ref_id = coalesce(excluded.participant_ref_id, booking_email_notifications.participant_ref_id),
                trigger_event = excluded.trigger_event,
                sent_event_id = excluded.sent_event_id,
                sent_at = excluded.sent_at,
                updated_at = now()
            """,
            {
                "booking_ref_id": booking_ref_id,
                "participant_ref_id": participant_ref_id,
                "email": email,
                "trigger_event": trigger_event if isinstance(trigger_event, str) else None,
                "job_id": job_id,
                "sent_event_id": event.event_id,
                "sent_at": event.occurred_at,
            },
        )

    def _handle_email_status(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
    ) -> tuple[str, dict[str, Any]] | None:
        """Handle unisender transactional status events."""
        event_data = event.payload.get("event_data")
        if not isinstance(event_data, dict):
            return None

        email = event_data.get("email")
        job_id = event_data.get("job_id")
        status = event_data.get("status")
        clicked_url = event_data.get("url")
        status_event_time = self._parse_iso_datetime(event_data.get("event_time"))

        if not isinstance(email, str) or not isinstance(job_id, str):
            return None

        return (
            """
            insert into booking_email_notifications (
                booking_ref_id,
                participant_ref_id,
                job_id,
                last_status,
                last_status_event_time,
                last_status_event_id,
                last_clicked_url,
                updated_at
            ) values (
                :booking_ref_id,
                (select id from participants where email = :email),
                :job_id,
                :last_status,
                :last_status_event_time,
                :last_status_event_id,
                :last_clicked_url,
                now()
            )
            on conflict (job_id) do update
            set
                booking_ref_id = excluded.booking_ref_id,
                participant_ref_id = coalesce(excluded.participant_ref_id, booking_email_notifications.participant_ref_id),
                last_status = excluded.last_status,
                last_status_event_time = excluded.last_status_event_time,
                last_status_event_id = excluded.last_status_event_id,
                last_clicked_url = coalesce(excluded.last_clicked_url, booking_email_notifications.last_clicked_url),
                updated_at = now()
            """,
            {
                "booking_ref_id": booking_ref_id,
                "email": email,
                "job_id": job_id,
                "last_status": status if isinstance(status, str) else None,
                "last_status_event_time": status_event_time,
                "last_status_event_id": event.event_id,
                "last_clicked_url": clicked_url if isinstance(clicked_url, str) else None,
            },
        )

    @staticmethod
    def _resolve_recipient_email(payload: dict[str, Any], role: str | None) -> str | None:
        """Extract recipient email from payload based on role."""
        direct_email = payload.get("email")
        if isinstance(direct_email, str) and direct_email:
            return direct_email

        if role == ParticipantRole.ORGANIZER:
            for key in ("user", "organizer"):
                participant = payload.get(key)
                if isinstance(participant, dict):
                    email = participant.get("email")
                    if isinstance(email, str) and email:
                        return email

        if role == ParticipantRole.CLIENT:
            participant = payload.get("client")
            if isinstance(participant, dict):
                email = participant.get("email")
                if isinstance(email, str) and email:
                    return email

        return None

    @staticmethod
    def _parse_iso_datetime(value: Any) -> datetime | None:
        """Parse ISO datetime string."""
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value:
            return None

        candidate = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None


class TelegramNotificationProjection(BaseProjection):
    """Projects telegram notification events to booking_telegram_notifications table.

    Handles: booking.events.v1.notification.telegram.message_sent.create
    """

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type == EventType.BOOKING_NOTIFICATION_TELEGRAM_MESSAGE_SENT

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        users = event.payload.get("users")
        role = users[0].get("role") if isinstance(users, list) and users else None
        trigger_event = event.payload.get("trigger_event")

        email = self._resolve_recipient_email(event.payload, role)

        participant_ref_id = organizer_ref_id if role == ParticipantRole.ORGANIZER else client_ref_id

        return (
            """
            insert into booking_telegram_notifications (
                booking_ref_id,
                participant_ref_id,
                trigger_event,
                sent_event_id,
                sent_at,
                updated_at
            ) values (
                :booking_ref_id,
                coalesce(:participant_ref_id, (select id from participants where email = :email)),
                :trigger_event,
                :sent_event_id,
                :sent_at,
                now()
            )
            on conflict (booking_ref_id, participant_ref_id, trigger_event) do update
            set
                sent_event_id = excluded.sent_event_id,
                sent_at = excluded.sent_at,
                updated_at = now()
            """,
            {
                "booking_ref_id": booking_ref_id,
                "participant_ref_id": participant_ref_id,
                "email": email,
                "trigger_event": trigger_event if isinstance(trigger_event, str) else None,
                "sent_event_id": event.event_id,
                "sent_at": event.occurred_at,
            },
        )

    @staticmethod
    def _resolve_recipient_email(payload: dict[str, Any], role: str | None) -> str | None:
        """Extract recipient email from payload based on role."""
        direct_email = payload.get("email")
        if isinstance(direct_email, str) and direct_email:
            return direct_email

        if role == ParticipantRole.ORGANIZER:
            for key in ("user", "organizer"):
                participant = payload.get(key)
                if isinstance(participant, dict):
                    email = participant.get("email")
                    if isinstance(email, str) and email:
                        return email

        return None


class EmailStatusHistoryProjection(BaseProjection):
    """Projects email status changes to booking_email_status_history table.

    Handles: unisender.events.v1.transactional.status.create
    """

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type == EventType.UNISENDER_TRANSACTIONAL_STATUS

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        event_data = event.payload.get("event_data")
        if not isinstance(event_data, dict):
            return None

        job_id = event_data.get("job_id")
        status = event_data.get("status")
        status_event_time = self._parse_iso_datetime(event_data.get("event_time"))

        if not isinstance(job_id, str) or not isinstance(status, str):
            return None

        return (
            """
            insert into booking_email_status_history (
                job_id,
                status,
                status_event_time,
                source_event_id,
                updated_at
            ) values (
                :job_id,
                :status,
                :status_event_time,
                :source_event_id,
                now()
            )
            on conflict (job_id, status) do update
            set
                status_event_time = excluded.status_event_time,
                source_event_id = excluded.source_event_id,
                updated_at = now()
            """,
            {
                "job_id": job_id,
                "status": status,
                "status_event_time": status_event_time,
                "source_event_id": event.event_id,
            },
        )

    @staticmethod
    def _parse_iso_datetime(value: Any) -> datetime | None:
        """Parse ISO datetime string."""
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value:
            return None

        candidate = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
