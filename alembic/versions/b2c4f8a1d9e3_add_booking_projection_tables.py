"""add_booking_projection_tables

Revision ID: b2c4f8a1d9e3
Revises: 3a791de67f88
Create Date: 2026-03-07 22:35:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b2c4f8a1d9e3"
down_revision: str | Sequence[str] | None = "3a791de67f88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "participants",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("time_zone", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="uq_participants_email"),
    )
    op.create_index("ix_participants_role", "participants", ["role"])

    op.create_table(
        "bookings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("booking_uid", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_status", sa.Text(), nullable=True),
        sa.Column("current_organizer_participant_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("current_client_participant_ref_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["current_organizer_participant_ref_id"],
            ["participants.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["current_client_participant_ref_id"],
            ["participants.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("booking_uid", name="uq_bookings_booking_uid"),
    )
    op.create_index(
        "ix_bookings_last_seen_desc",
        "bookings",
        [sa.text("last_seen_at DESC")],
    )

    op.create_table(
        "booking_organizer_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("booking_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("organizer_participant_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["booking_ref_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organizer_participant_ref_id"],
            ["participants.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["source_event_id"], ["events.event_id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_boh_booking_effective_from_desc",
        "booking_organizer_history",
        ["booking_ref_id", sa.text("effective_from DESC")],
    )

    op.create_table(
        "booking_meeting_links",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("booking_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("recipient_role", sa.Text(), nullable=False),
        sa.Column("participant_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("meeting_url", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["booking_ref_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_ref_id"], ["participants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_event_id"], ["events.event_id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "booking_ref_id",
            "recipient_role",
            name="uq_bml_booking_ref_id_recipient_role",
        ),
    )
    op.create_index(
        "ix_bml_booking_ref_id",
        "booking_meeting_links",
        ["booking_ref_id"],
    )

    op.create_table(
        "booking_email_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("booking_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("participant_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("recipient_role", sa.Text(), nullable=True),
        sa.Column("trigger_event", sa.Text(), nullable=True),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("sent_event_id", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.Text(), nullable=True),
        sa.Column("last_status_event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_event_id", sa.Text(), nullable=True),
        sa.Column("last_clicked_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["booking_ref_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_ref_id"], ["participants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sent_event_id"], ["events.event_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_status_event_id"], ["events.event_id"], ondelete="SET NULL"),
        sa.UniqueConstraint("job_id", name="uq_booking_email_notifications_job_id"),
    )
    op.create_index(
        "ix_ben_booking_ref_id",
        "booking_email_notifications",
        ["booking_ref_id"],
    )
    op.create_index(
        "ix_ben_booking_ref_last_status_time_desc",
        "booking_email_notifications",
        ["booking_ref_id", sa.text("last_status_event_time DESC")],
    )

    op.create_table(
        "booking_email_status_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("notification_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("status_event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_url", sa.Text(), nullable=True),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["notification_ref_id"],
            ["booking_email_notifications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["source_event_id"], ["events.event_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_event_id", name="uq_besh_source_event_id"),
    )
    op.create_index(
        "ix_besh_notification_ref_status_time_desc",
        "booking_email_status_history",
        ["notification_ref_id", sa.text("status_event_time DESC")],
    )

    op.create_table(
        "booking_telegram_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("booking_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("participant_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("recipient_role", sa.Text(), nullable=True),
        sa.Column("trigger_event", sa.Text(), nullable=True),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["booking_ref_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_ref_id"], ["participants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_event_id"], ["events.event_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_event_id", name="uq_btn_source_event_id"),
    )
    op.create_index(
        "ix_btn_booking_ref_sent_at_desc",
        "booking_telegram_notifications",
        ["booking_ref_id", sa.text("sent_at DESC")],
    )

    op.create_table(
        "booking_chat_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("booking_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_event_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("chat_event_type", sa.Text(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("participant_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("text_preview", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["booking_ref_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_ref_id"], ["participants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_event_id"], ["events.event_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("raw_event_id", name="uq_booking_chat_events_raw_event_id"),
    )
    op.create_index(
        "ix_bce_booking_ref_occurred_desc",
        "booking_chat_events",
        ["booking_ref_id", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_bce_booking_ref_type_occurred_desc",
        "booking_chat_events",
        ["booking_ref_id", "chat_event_type", sa.text("occurred_at DESC")],
    )

    op.create_table(
        "booking_video_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("booking_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_event_id", sa.Text(), nullable=False),
        sa.Column("video_event_type", sa.Text(), nullable=False),
        sa.Column("participant_role", sa.Text(), nullable=True),
        sa.Column("participant_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["booking_ref_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_ref_id"], ["participants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_event_id"], ["events.event_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("raw_event_id", name="uq_booking_video_events_raw_event_id"),
    )
    op.create_index(
        "ix_bve_booking_ref_event_time_desc",
        "booking_video_events",
        ["booking_ref_id", sa.text("event_time DESC")],
    )
    op.create_index(
        "ix_bve_booking_ref_type_event_time_desc",
        "booking_video_events",
        ["booking_ref_id", "video_event_type", sa.text("event_time DESC")],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_bve_booking_ref_type_event_time_desc", table_name="booking_video_events")
    op.drop_index("ix_bve_booking_ref_event_time_desc", table_name="booking_video_events")
    op.drop_table("booking_video_events")

    op.drop_index("ix_bce_booking_ref_type_occurred_desc", table_name="booking_chat_events")
    op.drop_index("ix_bce_booking_ref_occurred_desc", table_name="booking_chat_events")
    op.drop_table("booking_chat_events")

    op.drop_index("ix_besh_notification_ref_status_time_desc", table_name="booking_email_status_history")
    op.drop_table("booking_email_status_history")

    op.drop_index("ix_btn_booking_ref_sent_at_desc", table_name="booking_telegram_notifications")
    op.drop_table("booking_telegram_notifications")

    op.drop_index("ix_ben_booking_ref_last_status_time_desc", table_name="booking_email_notifications")
    op.drop_index("ix_ben_booking_ref_id", table_name="booking_email_notifications")
    op.drop_table("booking_email_notifications")

    op.drop_index("ix_bml_booking_ref_id", table_name="booking_meeting_links")
    op.drop_table("booking_meeting_links")

    op.drop_index("ix_boh_booking_effective_from_desc", table_name="booking_organizer_history")
    op.drop_table("booking_organizer_history")

    op.drop_index("ix_bookings_last_seen_desc", table_name="bookings")
    op.drop_table("bookings")

    op.drop_index("ix_participants_role", table_name="participants")
    op.drop_table("participants")
