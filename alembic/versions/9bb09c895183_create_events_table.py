"""create_events_table

Revision ID: 9bb09c895183
Revises:
Create Date: 2026-03-02 23:37:10.330377

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9bb09c895183"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("booking_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )

    op.create_index(
        "ix_events_booking_id_occurred_at_desc",
        "events",
        ["booking_id", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_events_event_type_occurred_at_desc",
        "events",
        ["event_type", sa.text("occurred_at DESC")],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_events_event_type_occurred_at_desc", table_name="events")
    op.drop_index("ix_events_booking_id_occurred_at_desc", table_name="events")
    op.drop_table("events")
