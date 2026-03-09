from typing import Any

from event_saver.event_types import SourceType
from event_saver.interfaces import IBookingEventClassifier


QUEUE_DOMAIN_MAP = {
    "events.booking.lifecycle": "booking",
    "events.booking.reminder": "booking",
    "events.chat.lifecycle": "chat",
    "events.chat.activity": "chat",
    "events.chat": "chat",
    "events.meeting.lifecycle": "meeting",
    "events.notification.delivery": "notification",
    "events.mail": "notification",
    "events.jitsi": "video",
}


class BookingTimelineClassifier(IBookingEventClassifier):
    def extract_action(
        self,
        *,
        queue_name: str,
        event_type: str,
        source: str,
        payload: dict[str, Any],
    ) -> str:
        extractor = {
            "events.chat": self._extract_action_by_queue_chat,
            "events.jitsi": self._extract_action_by_queue_jitsi,
        }.get(queue_name)
        if extractor and (extracted := extractor(event_type=event_type, source=source, payload=payload)):
            return extracted

        if extracted := self._extract_action_by_source(source=source, payload=payload):
            return extracted

        if extracted := self._extract_action_by_event_type(event_type=event_type):
            return extracted

        return event_type

    @staticmethod
    def _extract_action_by_source(source: str, payload: dict[str, Any]) -> str | None:
        if source == SourceType.GETSTREAM:
            return payload.get("type")
        return None

    @staticmethod
    def _extract_action_by_event_type(event_type: str) -> str | None:
        if event_type.startswith("jitsi.events.v1.") and event_type.endswith(".create"):
            return event_type[len("jitsi.events.v1.") : -len(".create")]

        if ".v1." in event_type and event_type.endswith(".create"):
            return event_type.split(".v1.", maxsplit=1)[1].rsplit(".create", maxsplit=1)[0]

        return None

    @staticmethod
    def _extract_action_by_queue_chat(event_type: str, source: str, payload: dict[str, Any]) -> str | None:
        if stream_type := payload.get("type"):
            return stream_type
        return None

    @staticmethod
    def _extract_action_by_queue_jitsi(event_type: str, source: str, payload: dict[str, Any]) -> str | None:
        del source, payload
        if event_type.startswith("jitsi.events.v1.") and event_type.endswith(".create"):
            return event_type[len("jitsi.events.v1.") : -len(".create")]
        return None
