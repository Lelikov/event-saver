"""add booking_lifecycle_events.

Revision ID: ca7326cf2ec5
Revises: 188a4a37868a
Create Date: 2026-04-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ca7326cf2ec5"
down_revision: str | Sequence[str] | None = "188a4a37868a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "booking_lifecycle_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("booking_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_event_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("organizer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("details", postgresql.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["booking_ref_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_event_id"], ["events.event_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("raw_event_id", name="uq_booking_lifecycle_events_raw_event_id"),
    )
    op.create_index(
        "ix_ble_booking_ref_occurred_at",
        "booking_lifecycle_events",
        ["booking_ref_id", sa.text("occurred_at")],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ble_booking_ref_occurred_at", table_name="booking_lifecycle_events")
    op.drop_table("booking_lifecycle_events")
