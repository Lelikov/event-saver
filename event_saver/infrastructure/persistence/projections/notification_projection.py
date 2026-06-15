"""Projections for notifications (email and telegram)."""

import uuid
from typing import Any

from event_schemas.types import EventType, RecipientRole

from event_saver.domain.models.event import ParsedEvent
from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.utils import parse_iso_datetime


def _user_id_for_role(
    *,
    role: Any,
    organizer_user_id: uuid.UUID | None,
    client_user_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Map a recipient role to the corresponding participant UUID."""
    if role == RecipientRole.ORGANIZER:
        return organizer_user_id
    if role == RecipientRole.CLIENT:
        return client_user_id
    return None


class EmailNotificationProjection(BaseProjection):
    """Projects email notification events to booking_email_notifications table."""

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type in {
            EventType.NOTIFICATION_EMAIL_SENT,
            EventType.UNISENDER_STATUS_CREATED,
        }

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        if event.event_type == EventType.NOTIFICATION_EMAIL_SENT:
            return self._handle_email_sent(
                event=event,
                booking_ref_id=booking_ref_id,
                organizer_user_id=organizer_user_id,
                client_user_id=client_user_id,
            )

        if event.event_type == EventType.UNISENDER_STATUS_CREATED:
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
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
    ) -> tuple[str, dict[str, Any]] | None:
        original = event.payload.get("original", event.payload)
        job_id = original.get("job_id")
        if not isinstance(job_id, str):
            return None

        role = original.get("recipient_role")
        trigger_event = original.get("trigger_event")
        email = original.get("email")

        user_id = _user_id_for_role(
            role=role,
            organizer_user_id=organizer_user_id,
            client_user_id=client_user_id,
        )

        return (
            """
            insert into booking_email_notifications (
                booking_ref_id,
                user_id,
                trigger_event,
                job_id,
                sent_event_id,
                sent_at,
                recipient_email,
                updated_at
            ) values (
                :booking_ref_id,
                :user_id,
                :trigger_event,
                :job_id,
                :sent_event_id,
                :sent_at,
                :recipient_email,
                now()
            )
            on conflict (job_id) do update
            set
                booking_ref_id = excluded.booking_ref_id,
                user_id = coalesce(excluded.user_id, booking_email_notifications.user_id),
                trigger_event = excluded.trigger_event,
                sent_event_id = excluded.sent_event_id,
                sent_at = excluded.sent_at,
                recipient_email = coalesce(excluded.recipient_email, booking_email_notifications.recipient_email),
                updated_at = now()
            """,
            {
                "booking_ref_id": booking_ref_id,
                "user_id": str(user_id) if user_id is not None else None,
                "trigger_event": trigger_event if isinstance(trigger_event, str) else None,
                "job_id": job_id,
                "sent_event_id": event.event_id,
                "sent_at": event.occurred_at,
                "recipient_email": email if isinstance(email, str) else None,
            },
        )

    def _handle_email_status(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
    ) -> tuple[str, dict[str, Any]] | None:
        original = event.payload.get("original", event.payload)
        event_data = original.get("event_data")
        if not isinstance(event_data, dict):
            return None

        job_id = event_data.get("job_id")
        status = event_data.get("status")
        clicked_url = event_data.get("url")
        status_event_time = parse_iso_datetime(event_data.get("event_time"))
        email = event_data.get("email")

        if not isinstance(job_id, str):
            return None

        return (
            """
            insert into booking_email_notifications (
                booking_ref_id,
                user_id,
                job_id,
                last_status,
                last_status_event_time,
                last_status_event_id,
                last_clicked_url,
                recipient_email,
                updated_at
            ) values (
                :booking_ref_id,
                NULL,
                :job_id,
                :last_status,
                :last_status_event_time,
                :last_status_event_id,
                :last_clicked_url,
                :recipient_email,
                now()
            )
            on conflict (job_id) do update
            set
                booking_ref_id = excluded.booking_ref_id,
                last_status = excluded.last_status,
                last_status_event_time = excluded.last_status_event_time,
                last_status_event_id = excluded.last_status_event_id,
                last_clicked_url = coalesce(excluded.last_clicked_url, booking_email_notifications.last_clicked_url),
                recipient_email = coalesce(excluded.recipient_email, booking_email_notifications.recipient_email),
                updated_at = now()
            """,
            {
                "booking_ref_id": booking_ref_id,
                "job_id": job_id,
                "last_status": status if isinstance(status, str) else None,
                "last_status_event_time": status_event_time,
                "last_status_event_id": event.event_id,
                "last_clicked_url": clicked_url if isinstance(clicked_url, str) else None,
                "recipient_email": email if isinstance(email, str) else None,
            },
        )


class TelegramNotificationProjection(BaseProjection):
    """Projects telegram notification events to booking_telegram_notifications table."""

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type == EventType.NOTIFICATION_TELEGRAM_SENT

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        original = event.payload.get("original", event.payload)
        role = original.get("recipient_role")
        trigger_event = original.get("trigger_event")
        email = original.get("email")

        # Notification delivery-result events do not carry normalized.participants,
        # so organizer_user_id/client_user_id are None here and user_id may stay
        # NULL — still record the notification (keyed by recipient_email + role),
        # matching the email projection. Otherwise telegram rows are never created.
        user_id = _user_id_for_role(
            role=role,
            organizer_user_id=organizer_user_id,
            client_user_id=client_user_id,
        )

        return (
            """
            insert into booking_telegram_notifications (
                booking_ref_id,
                user_id,
                trigger_event,
                source_event_id,
                sent_at,
                recipient_email
            ) values (
                :booking_ref_id,
                :user_id,
                :trigger_event,
                :source_event_id,
                :sent_at,
                :recipient_email
            )
            on conflict (source_event_id) do nothing
            """,
            {
                "booking_ref_id": booking_ref_id,
                "user_id": str(user_id) if user_id is not None else None,
                "trigger_event": trigger_event if isinstance(trigger_event, str) else None,
                "source_event_id": event.event_id,
                "sent_at": event.occurred_at,
                "recipient_email": email if isinstance(email, str) else None,
            },
        )


class EmailStatusHistoryProjection(BaseProjection):
    """Projects email status changes to booking_email_status_history table."""

    def can_handle(self, event: ParsedEvent) -> bool:
        return event.event_type == EventType.UNISENDER_STATUS_CREATED

    async def handle(
        self,
        *,
        event: ParsedEvent,
        booking_ref_id: int,
        organizer_user_id: uuid.UUID | None,
        client_user_id: uuid.UUID | None,
        queue_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        original = event.payload.get("original", event.payload)
        event_data = original.get("event_data")
        if not isinstance(event_data, dict):
            return None

        job_id = event_data.get("job_id")
        status = event_data.get("status")
        status_event_time = parse_iso_datetime(event_data.get("event_time"))

        if not isinstance(job_id, str) or not isinstance(status, str):
            return None

        clicked_url = event_data.get("url")

        return (
            """
            insert into booking_email_status_history (
                notification_ref_id,
                status,
                status_event_time,
                clicked_url,
                source_event_id
            )
            select ben.id, :status, :status_event_time, :clicked_url, :source_event_id
            from booking_email_notifications ben
            where ben.job_id = :job_id
            on conflict (source_event_id) do nothing
            """,
            {
                "job_id": job_id,
                "status": status,
                "status_event_time": status_event_time,
                "clicked_url": clicked_url if isinstance(clicked_url, str) else None,
                "source_event_id": event.event_id,
            },
        )
