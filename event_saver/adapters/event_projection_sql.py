import hashlib
from datetime import UTC, datetime
from typing import Any

import ujson

from event_saver.event_types import EventType, ParticipantRole, SourceType
from event_saver.interfaces.projection import IBookingEventClassifier, IEventProjectionStatementFactory
from event_saver.utils import decode_user_id


def _parse_iso_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None

    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


class EventProjectionStatementFactory(IEventProjectionStatementFactory):
    def __init__(
        self,
        classifier: IBookingEventClassifier,
        getstream_user_id_encryption_key: str | None = None,
    ) -> None:
        self._classifier = classifier
        self._getstream_user_id_encryption_key = getstream_user_id_encryption_key

    def build_projection_statements(
        self,
        *,
        queue_name: str,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        event_id: str,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> list[tuple[str, dict[str, Any]]]:
        statements: list[tuple[str, dict[str, Any]]] = []

        for statement in (
            self._build_meeting_link_statement(
                booking_ref_id=booking_ref_id,
                organizer_ref_id=organizer_ref_id,
                client_ref_id=client_ref_id,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
            ),
            self._build_email_notification_statement(
                booking_ref_id=booking_ref_id,
                organizer_ref_id=organizer_ref_id,
                client_ref_id=client_ref_id,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
            ),
            self._build_telegram_notification_statement(
                booking_ref_id=booking_ref_id,
                organizer_ref_id=organizer_ref_id,
                client_ref_id=client_ref_id,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
            ),
            self._build_email_status_history_statement(
                event_id=event_id,
                event_type=event_type,
                payload=payload,
            ),
            self._build_chat_event_statement(
                queue_name=queue_name,
                booking_ref_id=booking_ref_id,
                organizer_ref_id=organizer_ref_id,
                client_ref_id=client_ref_id,
                event_id=event_id,
                source=source,
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
            ),
            self._build_video_event_statement(
                queue_name=queue_name,
                booking_ref_id=booking_ref_id,
                organizer_ref_id=organizer_ref_id,
                client_ref_id=client_ref_id,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
            ),
            self._build_chat_read_update_statements(
                booking_ref_id=booking_ref_id,
                source=source,
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
            ),
        ):
            if statement is not None:
                statements.append(statement)

        return statements

    @staticmethod
    def _build_meeting_link_statement(
        *,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> tuple[str, dict[str, Any]] | None:
        if event_type != EventType.BOOKING_MEETING_URL_CREATED:
            return None

        meeting_url = payload.get("meeting_url")

        participant_ref_id = organizer_ref_id or client_ref_id

        return (
            """
            insert into booking_meeting_links (
                booking_ref_id,
                participant_ref_id,
                meeting_url,
                source_event_id,
                occurred_at,
                updated_at
            ) values (
                :booking_ref_id,
                :participant_ref_id,
                :meeting_url,
                :source_event_id,
                :occurred_at,
                now()
            )
            on conflict (booking_ref_id, participant_ref_id) do update
            set
                participant_ref_id = excluded.participant_ref_id,
                meeting_url = excluded.meeting_url,
                source_event_id = excluded.source_event_id,
                occurred_at = excluded.occurred_at,
                updated_at = now()
            """,
            {
                "booking_ref_id": booking_ref_id,
                "participant_ref_id": participant_ref_id,
                "meeting_url": meeting_url,
                "source_event_id": event_id,
                "occurred_at": occurred_at,
            },
        )

    @staticmethod
    def _build_email_notification_statement(
        *,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> tuple[str, dict[str, Any]] | None:
        if event_type == EventType.BOOKING_NOTIFICATION_EMAIL_MESSAGE_SENT:
            job_id = payload.get("job_id")
            role = payload["users"][0].get("role") if payload.get("users") else None
            trigger_event = payload.get("trigger_event")
            email = _resolve_recipient_email(
                payload=payload,
                recipient_role=role if isinstance(role, str) else None,
            )
            if not isinstance(job_id, str):
                return None

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
                    "sent_event_id": event_id,
                    "sent_at": occurred_at,
                },
            )

        if event_type == EventType.UNISENDER_TRANSACTIONAL_STATUS:
            event_data = payload.get("event_data")
            if not isinstance(event_data, dict):
                return None

            email = event_data.get("email")
            job_id = event_data.get("job_id")
            status = event_data.get("status")
            clicked_url = event_data.get("url")
            status_event_time = _parse_iso_datetime(event_data.get("event_time"))
            if not isinstance(email, str) or not isinstance(job_id, str):
                return None

            participant_ref_id = None

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
                    coalesce(:participant_ref_id, (select id from participants where email = :email)),
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
                    "participant_ref_id": participant_ref_id,
                    "email": email,
                    "job_id": job_id,
                    "last_status": status if isinstance(status, str) else None,
                    "last_status_event_time": status_event_time,
                    "last_status_event_id": event_id,
                    "last_clicked_url": clicked_url if isinstance(clicked_url, str) else None,
                },
            )

        return None

    @staticmethod
    def _build_telegram_notification_statement(
        *,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> tuple[str, dict[str, Any]] | None:
        if event_type != EventType.BOOKING_NOTIFICATION_TELEGRAM_MESSAGE_SENT:
            return None

        trigger_event = payload.get("trigger_event")
        participant_ref_id = organizer_ref_id or client_ref_id

        return (
            """
            insert into booking_telegram_notifications (
                booking_ref_id,
                participant_ref_id,
                trigger_event,
                source_event_id,
                sent_at
            ) values (
                :booking_ref_id,
                :participant_ref_id,
                :trigger_event,
                :source_event_id,
                :sent_at
            )
            on conflict (source_event_id) do nothing
            """,
            {
                "booking_ref_id": booking_ref_id,
                "participant_ref_id": participant_ref_id,
                "trigger_event": trigger_event if isinstance(trigger_event, str) else None,
                "source_event_id": event_id,
                "sent_at": occurred_at,
            },
        )

    @staticmethod
    def _build_email_status_history_statement(
        *,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any]] | None:
        if event_type != EventType.UNISENDER_TRANSACTIONAL_STATUS:
            return None

        event_data = payload.get("event_data")
        if not isinstance(event_data, dict):
            return None

        job_id = event_data.get("job_id")
        status = event_data.get("status")
        clicked_url = event_data.get("url")
        if not isinstance(job_id, str):
            return None

        return (
            """
            insert into booking_email_status_history (
                notification_ref_id,
                status,
                status_event_time,
                clicked_url,
                source_event_id
            )
            select
                ben.id,
                :status,
                :status_event_time,
                :clicked_url,
                :source_event_id
            from booking_email_notifications ben
            where ben.job_id = :job_id
            on conflict (source_event_id) do nothing
            """,
            {
                "job_id": job_id,
                "status": status if isinstance(status, str) else None,
                "status_event_time": _parse_iso_datetime(event_data.get("event_time")),
                "clicked_url": clicked_url if isinstance(clicked_url, str) else None,
                "source_event_id": event_id,
            },
        )

    def _build_chat_event_statement(
        self,
        *,
        queue_name: str,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        event_id: str,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> tuple[str, dict[str, Any]] | None:
        if source not in {SourceType.BOOKING, SourceType.GETSTREAM}:
            return None
        if ".chat." not in event_type and source != SourceType.GETSTREAM:
            return None

        chat_event_type = self._classifier.extract_action(
            queue_name=queue_name,
            event_type=event_type,
            source=source,
            payload=payload,
        )

        message_id = payload.get("message_id")
        if not isinstance(message_id, str):
            message = payload.get("message")
            if isinstance(message, dict):
                msg_id = message.get("id")
                message_id = msg_id if isinstance(msg_id, str) else None
            else:
                message_id = None

        participant_email = _extract_chat_participant_email(
            source=source,
            payload=payload,
            decode_user_id=self._decode_user_id,
        )
        participant_ref_id = _extract_chat_participant_ref_id(
            payload=payload,
            organizer_ref_id=organizer_ref_id,
            client_ref_id=client_ref_id,
        )

        text_preview = None
        message = payload.get("message")
        if isinstance(message, dict):
            text = message.get("text")
            if isinstance(text, str):
                text_preview = text[:512]

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
                "raw_event_id": event_id,
                "provider": source,
                "chat_event_type": chat_event_type,
                "message_id": message_id,
                "participant_ref_id": participant_ref_id,
                "participant_email": participant_email,
                "is_read": None,
                "text_preview": text_preview,
                "occurred_at": occurred_at,
            },
        )

    def _build_chat_read_update_statements(
        self,
        *,
        booking_ref_id: int,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> tuple[str, dict] | None:
        if source != SourceType.GETSTREAM or event_type != EventType.GETSTREAM_MESSAGE_READ:
            return None

        participant_email = _extract_chat_participant_email(
            source=source,
            payload=payload,
            decode_user_id=self._decode_user_id,
        )

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
                "last_read_message_id": payload.get("last_read_message_id"),
                "read_occurred_at": occurred_at,
            },
        )

    def _decode_user_id(self, *, encoded_user_id: str) -> str:
        try:
            return decode_user_id(
                encoded_user_id=encoded_user_id,
                encryption_key=hashlib.sha256(self._getstream_user_id_encryption_key.encode()).digest(),
            )
        except Exception:
            return encoded_user_id

    def _build_video_event_statement(
        self,
        *,
        queue_name: str,
        booking_ref_id: int,
        organizer_ref_id: int | None,
        client_ref_id: int | None,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> tuple[str, dict[str, Any]] | None:
        if not event_type.startswith("jitsi.events.v1."):
            return None

        context = payload.get("context")
        if not isinstance(context, dict):
            context = {}

        context_user = context.get("user", {})
        if not isinstance(context_user, dict):
            context_user = {}

        participant_role = context_user.get("role")
        participant_role_raw = context_user.get("role")
        participant_ref_id = None
        if participant_role_raw == "organizer":
            participant_ref_id = organizer_ref_id
        elif participant_role_raw == "client":
            participant_ref_id = client_ref_id

        video_event_type = self._classifier.extract_action(
            queue_name=queue_name,
            event_type=event_type,
            source=SourceType.JITSI,
            payload=payload,
        )

        projected_payload = _project_video_payload(
            video_event_type=video_event_type,
            payload=payload,
        )

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
                "raw_event_id": event_id,
                "video_event_type": video_event_type,
                "participant_role": participant_role if isinstance(participant_role, str) else None,
                "participant_ref_id": participant_ref_id,
                "event_time": _parse_iso_datetime(payload.get("time")),
                "payload": ujson.dumps(projected_payload),
            },
        )


def _project_video_payload(*, video_event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if video_event_type in {"audioMuteStatusChanged", "videoMuteStatusChanged"}:
        muted = payload.get("muted")
        return {"muted": muted} if isinstance(muted, bool) else {}

    if video_event_type == "deviceListChanged":
        devices = payload.get("devices")
        return {"devices": devices} if isinstance(devices, dict) else {}

    if video_event_type in {"videoConferenceJoined", "videoConferenceLeft"}:
        return {}

    return payload


def _resolve_recipient_email(*, payload: dict[str, Any], recipient_role: str | None) -> str | None:
    direct_email = payload.get("email")
    if isinstance(direct_email, str) and direct_email:
        return direct_email

    if recipient_role == ParticipantRole.ORGANIZER:
        for key in ("user", "organizer"):
            participant = payload.get(key)
            if isinstance(participant, dict):
                email = participant.get("email")
                if isinstance(email, str) and email:
                    return email
    elif recipient_role == ParticipantRole.CLIENT:
        participant = payload.get("client")
        if isinstance(participant, dict):
            email = participant.get("email")
            if isinstance(email, str) and email:
                return email

    return None


def _extract_chat_participant_ref_id(
    *,
    payload: dict[str, Any],
    organizer_ref_id: int | None,
    client_ref_id: int | None,
) -> int | None:
    users = payload.get("users")
    if isinstance(users, list) and users:
        first_user = users[0]
        if isinstance(first_user, dict):
            role = first_user.get("role")
            if role == ParticipantRole.ORGANIZER:
                return organizer_ref_id
            if role == ParticipantRole.CLIENT:
                return client_ref_id
    return None


def _extract_chat_participant_email(
    *,
    source: str,
    payload: dict[str, Any],
    decode_user_id: Any,
) -> str | None:
    users = payload.get("users")
    if isinstance(users, list) and users:
        first_user = users[0]
        if isinstance(first_user, dict):
            email = first_user.get("email")
            if isinstance(email, str) and email:
                return email

    user_id = payload.get("user_id")
    if isinstance(user_id, str) and "@" in user_id:
        return user_id

    user = payload.get("user")
    if isinstance(user, dict):
        raw_id = user.get("id")
        if isinstance(raw_id, str) and raw_id:
            if source == SourceType.GETSTREAM:
                decoded = decode_user_id(encoded_user_id=raw_id)
                return decoded if isinstance(decoded, str) and "@" in decoded else None
            return raw_id if "@" in raw_id else None

    return None
