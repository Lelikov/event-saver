"""add_hash_to_events

Revision ID: 5f1c2e9a8b1d
Revises: 9bb09c895183
Create Date: 2026-03-03 21:59:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5f1c2e9a8b1d"
down_revision: str | Sequence[str] | None = "9bb09c895183"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("events", sa.Column("hash", sa.Text(), nullable=True))

    op.execute("update events set hash = md5(payload::text)")

    op.execute(
        """
        with ranked as (
            select
                ctid,
                row_number() over (
                    partition by booking_id, event_type, source, hash
                    order by received_at asc, event_id asc
                ) as rn
            from events
        )
        delete from events e
        using ranked r
        where e.ctid = r.ctid
          and r.rn > 1
        """,
    )

    op.alter_column("events", "hash", nullable=False)
    op.create_index(
        "uq_events_booking_id_event_type_source_hash",
        "events",
        ["booking_id", "event_type", "source", "hash"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_events_booking_id_event_type_source_hash", table_name="events")
    op.drop_column("events", "hash")
