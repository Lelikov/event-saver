from typing import Any

from event_schemas.types import EventType, SourceType

from event_saver.interfaces import IBookingEventClassifier


_JITSI_PREFIX = "jitsi."

_JITSI_EVENT_TYPES: frozenset[str] = frozenset(et.value for et in EventType if et.value.startswith(_JITSI_PREFIX))

_UNISENDER_ACTION_MAP: dict[str, str] = {
    EventType.UNISENDER_STATUS_CREATED: "transactional.status",
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
            original = payload.get("original", payload)
            return original.get("type")
        return None

    @staticmethod
    def _extract_action_by_event_type(event_type: str) -> str | None:
        if action := _UNISENDER_ACTION_MAP.get(event_type):
            return action
        return None

    @staticmethod
    def _extract_action_by_queue_chat(*, payload: dict[str, Any], **_: Any) -> str | None:
        original = payload.get("original", payload)
        if stream_type := original.get("type"):
            return stream_type
        return None

    @staticmethod
    def _extract_action_by_queue_jitsi(*, event_type: str, **_: Any) -> str | None:
        if event_type in _JITSI_EVENT_TYPES:
            return event_type.removeprefix(_JITSI_PREFIX)
        return None
