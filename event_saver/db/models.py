from datetime import datetime

from sqlalchemy import DateTime, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from event_saver.db.base import Base


class Event(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    booking_id: Mapped[str] = mapped_column(Text, nullable=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    hash: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index(
            "ix_events_booking_id_occurred_at_desc",
            "booking_id",
            text("occurred_at DESC"),
        ),
        Index(
            "ix_events_event_type_occurred_at_desc",
            "event_type",
            text("occurred_at DESC"),
        ),
        Index(
            "uq_events_booking_id_event_type_source_hash",
            "booking_id",
            "event_type",
            "source",
            "hash",
            unique=True,
        ),
    )
