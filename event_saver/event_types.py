from enum import StrEnum


class SourceType(StrEnum):
    BOOKING = "booking"
    GETSTREAM = "getstream"
    UNISENDER_GO = "unisender-go"
    JITSI = "jitsi"


class ParticipantRole(StrEnum):
    ORGANIZER = "organizer"
    CLIENT = "client"


class EventType(StrEnum):
    GETSTREAM_MESSAGE_NEW = "getstream.events.v1.message.new.create"
    GETSTREAM_CHANNEL_CREATED = "getstream.events.v1.channel.created.create"
    GETSTREAM_CHANNEL_DELETED = "getstream.events.v1.channel.deleted.create"

    BOOKING_MEETING_URL_CREATED = "booking.events.v1.meeting.url_created.create"
    BOOKING_MEETING_URL_DELETED = "booking.events.v1.meeting.url_deleted.create"

    BOOKING_CREATED = "booking.events.v1.booking.created.create"
    BOOKING_CANCELLED = "booking.events.v1.booking.cancelled.create"
    BOOKING_REASSIGNED = "booking.events.v1.booking.reassigned.create"

    BOOKING_NOTIFICATION_EMAIL_MESSAGE_SENT = "booking.events.v1.notification.email.message_sent.create"
    BOOKING_NOTIFICATION_TELEGRAM_MESSAGE_SENT = "booking.events.v1.notification.telegram.message_sent.create"

    UNISENDER_TRANSACTIONAL_STATUS = "unisender.events.v1.transactional.status.create"
