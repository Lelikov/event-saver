from event_saver.infrastructure.persistence.projections.base import BaseProjection
from event_saver.infrastructure.persistence.projections.chat_projection import (
    ChatEventProjection,
    ChatReadUpdateProjection,
)
from event_saver.infrastructure.persistence.projections.meeting_projection import MeetingLinkProjection
from event_saver.infrastructure.persistence.projections.notification_projection import (
    EmailNotificationProjection,
    EmailStatusHistoryProjection,
    TelegramNotificationProjection,
)
from event_saver.infrastructure.persistence.projections.video_projection import VideoEventProjection


__all__ = [
    "BaseProjection",
    "ChatEventProjection",
    "ChatReadUpdateProjection",
    "EmailNotificationProjection",
    "EmailStatusHistoryProjection",
    "MeetingLinkProjection",
    "TelegramNotificationProjection",
    "VideoEventProjection",
]
