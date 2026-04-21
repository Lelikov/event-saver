"""Projections for notifications (email and telegram)."""

import uuid
from typing import Any

from event_schemas.types import EventType, RecipientRole

from event_saver.domain.models.event import ParsedEvent
from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.utils import parse_iso_datetime


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
        job_id = event.payload.get("job_id")
        if not isinstance(job_id, str):
            return None

        users = event.payload.get("users")
        role = users[0].get("role") if isinstance(users, list) and users else None
        trigger_event = event.payload.get("trigger_event")

        user_id = (
            organizer_user_id
            if role == RecipientRole.ORGANIZER
            else client_user_id
            if role == RecipientRole.CLIENT
            else None
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
                updated_at
            ) values (
                :booking_ref_id,
                :user_id,
                :trigger_event,
                :job_id,
                :sent_event_id,
                :sent_at,
                now()
            )
            on conflict (job_id) do update
            set
                booking_ref_id = excluded.booking_ref_id,
                user_id = coalesce(excluded.user_id, booking_email_notifications.user_id),
                trigger_event = excluded.trigger_event,
                sent_event_id = excluded.sent_event_id,
                sent_at = excluded.sent_at,
                updated_at = now()
            """,
            {
                "booking_ref_id": booking_ref_id,
                "user_id": str(user_id) if user_id is not None else None,
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
        event_data = event.payload.get("event_data")
        if not isinstance(event_data, dict):
            return None

        job_id = event_data.get("job_id")
        status = event_data.get("status")
        clicked_url = event_data.get("url")
        status_event_time = parse_iso_datetime(event_data.get("event_time"))

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
                updated_at
            ) values (
                :booking_ref_id,
                NULL,
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
                last_status = excluded.last_status,
                last_status_event_time = excluded.last_status_event_time,
                last_status_event_id = excluded.last_status_event_id,
                last_clicked_url = coalesce(excluded.last_clicked_url, booking_email_notifications.last_clicked_url),
                updated_at = now()
            """,
            {
                "booking_ref_id": booking_ref_id,
                "job_id": job_id,
                "last_status": status if isinstance(status, str) else None,
                "last_status_event_time": status_event_time,
                "last_status_event_id": event.event_id,
                "last_clicked_url": clicked_url if isinstance(clicked_url, str) else None,
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
        users = event.payload.get("users")
        role = users[0].get("role") if isinstance(users, list) and users else None
        trigger_event = event.payload.get("trigger_event")

        user_id = organizer_user_id if role == RecipientRole.ORGANIZER else client_user_id

        if user_id is None:
            return None

        return (
            """
            insert into booking_telegram_notifications (
                booking_ref_id,
                user_id,
                trigger_event,
                sent_event_id,
                sent_at,
                updated_at
            ) values (
                :booking_ref_id,
                :user_id,
                :trigger_event,
                :sent_event_id,
                :sent_at,
                now()
            )
            on conflict (booking_ref_id, user_id, trigger_event) do update
            set
                sent_event_id = excluded.sent_event_id,
                sent_at = excluded.sent_at,
                updated_at = now()
            """,
            {
                "booking_ref_id": booking_ref_id,
                "user_id": str(user_id) if user_id is not None else None,
                "trigger_event": trigger_event if isinstance(trigger_event, str) else None,
                "sent_event_id": event.event_id,
                "sent_at": event.occurred_at,
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
        event_data = event.payload.get("event_data")
        if not isinstance(event_data, dict):
            return None

        job_id = event_data.get("job_id")
        status = event_data.get("status")
        status_event_time = parse_iso_datetime(event_data.get("event_time"))

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
