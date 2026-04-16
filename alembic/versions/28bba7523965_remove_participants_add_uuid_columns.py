"""remove_participants_add_uuid_columns.

Revision ID: 28bba7523965
Revises: f3a9b2c1d4e5
Create Date: 2026-04-16 23:04:56.889366

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "28bba7523965"
down_revision: str | Sequence[str] | None = "f3a9b2c1d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Steps:
    1. Drop FK constraints referencing participants.id
    2. Drop old integer participant_ref_id columns (and associated unique constraints)
    3. Add new UUID columns
    4. Drop the participants table
    """
    # -------------------------------------------------------------------------
    # Step 1: Drop FK constraints referencing participants.id
    # PostgreSQL auto-generates constraint names as {table}_{column}_fkey
    # -------------------------------------------------------------------------
    op.drop_constraint(
        "bookings_current_organizer_participant_ref_id_fkey",
        "bookings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "bookings_current_client_participant_ref_id_fkey",
        "bookings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "booking_organizer_history_organizer_participant_ref_id_fkey",
        "booking_organizer_history",
        type_="foreignkey",
    )
    op.drop_constraint(
        "booking_meeting_links_participant_ref_id_fkey",
        "booking_meeting_links",
        type_="foreignkey",
    )
    op.drop_constraint(
        "booking_email_notifications_participant_ref_id_fkey",
        "booking_email_notifications",
        type_="foreignkey",
    )
    op.drop_constraint(
        "booking_telegram_notifications_participant_ref_id_fkey",
        "booking_telegram_notifications",
        type_="foreignkey",
    )
    op.drop_constraint(
        "booking_chat_events_participant_ref_id_fkey",
        "booking_chat_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "booking_video_events_participant_ref_id_fkey",
        "booking_video_events",
        type_="foreignkey",
    )

    # -------------------------------------------------------------------------
    # Step 2: Drop old integer columns (and associated unique constraints)
    # -------------------------------------------------------------------------
    op.drop_column("bookings", "current_organizer_participant_ref_id")
    op.drop_column("bookings", "current_client_participant_ref_id")

    op.drop_column("booking_organizer_history", "organizer_participant_ref_id")

    # Drop the unique constraint on (booking_ref_id, participant_ref_id) before dropping column
    op.drop_constraint(
        "uq_bml_booking_ref_id_participant_ref_id",
        "booking_meeting_links",
        type_="unique",
    )
    op.drop_column("booking_meeting_links", "participant_ref_id")

    op.drop_column("booking_email_notifications", "participant_ref_id")
    op.drop_column("booking_telegram_notifications", "participant_ref_id")
    op.drop_column("booking_chat_events", "participant_ref_id")
    op.drop_column("booking_video_events", "participant_ref_id")

    # -------------------------------------------------------------------------
    # Step 3: Add new UUID columns
    # -------------------------------------------------------------------------
    op.add_column(
        "bookings",
        sa.Column("organizer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("client_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.add_column(
        "booking_organizer_history",
        sa.Column("organizer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.add_column(
        "booking_meeting_links",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_bml_booking_ref_id_user_id",
        "booking_meeting_links",
        ["booking_ref_id", "user_id"],
    )

    op.add_column(
        "booking_email_notifications",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.add_column(
        "booking_telegram_notifications",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.add_column(
        "booking_chat_events",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.add_column(
        "booking_video_events",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # -------------------------------------------------------------------------
    # Step 4: Drop the participants table (and its indexes)
    # -------------------------------------------------------------------------
    op.drop_index("ix_participants_user_id", table_name="participants")
    op.drop_table("participants")


def downgrade() -> None:
    """Downgrade schema.

    Steps:
    1. Recreate participants table
    2. Drop UUID columns added in upgrade
    3. Re-add old integer columns (nullable)
    4. Re-add FK constraints
    5. Re-add old unique constraint on booking_meeting_links
    """
    # -------------------------------------------------------------------------
    # Step 1: Recreate participants table with schema as of f3a9b2c1d4e5
    # -------------------------------------------------------------------------
    op.create_table(
        "participants",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.UniqueConstraint("email", "role", name="uq_participants_email_role"),
        sa.UniqueConstraint("user_id", name="uq_participants_user_id"),
    )
    op.create_index("ix_participants_user_id", "participants", ["user_id"])

    # -------------------------------------------------------------------------
    # Step 2: Drop UUID columns added during upgrade
    # -------------------------------------------------------------------------
    op.drop_column("bookings", "organizer_user_id")
    op.drop_column("bookings", "client_user_id")

    op.drop_column("booking_organizer_history", "organizer_user_id")

    op.drop_constraint(
        "uq_bml_booking_ref_id_user_id",
        "booking_meeting_links",
        type_="unique",
    )
    op.drop_column("booking_meeting_links", "user_id")

    op.drop_column("booking_email_notifications", "user_id")
    op.drop_column("booking_telegram_notifications", "user_id")
    op.drop_column("booking_chat_events", "user_id")
    op.drop_column("booking_video_events", "user_id")

    # -------------------------------------------------------------------------
    # Step 3: Re-add old integer columns (nullable — we can't restore data)
    # -------------------------------------------------------------------------
    op.add_column(
        "bookings",
        sa.Column("current_organizer_participant_ref_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("current_client_participant_ref_id", sa.BigInteger(), nullable=True),
    )

    op.add_column(
        "booking_organizer_history",
        sa.Column("organizer_participant_ref_id", sa.BigInteger(), nullable=True),
    )

    op.add_column(
        "booking_meeting_links",
        sa.Column("participant_ref_id", sa.BigInteger(), nullable=True),
    )

    op.add_column(
        "booking_email_notifications",
        sa.Column("participant_ref_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "booking_telegram_notifications",
        sa.Column("participant_ref_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "booking_chat_events",
        sa.Column("participant_ref_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "booking_video_events",
        sa.Column("participant_ref_id", sa.BigInteger(), nullable=True),
    )

    # -------------------------------------------------------------------------
    # Step 4: Re-add FK constraints
    # -------------------------------------------------------------------------
    op.create_foreign_key(
        "bookings_current_organizer_participant_ref_id_fkey",
        "bookings",
        "participants",
        ["current_organizer_participant_ref_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "bookings_current_client_participant_ref_id_fkey",
        "bookings",
        "participants",
        ["current_client_participant_ref_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "booking_organizer_history_organizer_participant_ref_id_fkey",
        "booking_organizer_history",
        "participants",
        ["organizer_participant_ref_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "booking_meeting_links_participant_ref_id_fkey",
        "booking_meeting_links",
        "participants",
        ["participant_ref_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "booking_email_notifications_participant_ref_id_fkey",
        "booking_email_notifications",
        "participants",
        ["participant_ref_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "booking_telegram_notifications_participant_ref_id_fkey",
        "booking_telegram_notifications",
        "participants",
        ["participant_ref_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "booking_chat_events_participant_ref_id_fkey",
        "booking_chat_events",
        "participants",
        ["participant_ref_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "booking_video_events_participant_ref_id_fkey",
        "booking_video_events",
        "participants",
        ["participant_ref_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # -------------------------------------------------------------------------
    # Step 5: Re-add old unique constraint on booking_meeting_links
    # -------------------------------------------------------------------------
    op.create_unique_constraint(
        "uq_bml_booking_ref_id_participant_ref_id",
        "booking_meeting_links",
        ["booking_ref_id", "participant_ref_id"],
    )
