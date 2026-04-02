"""add tracing and idempotency columns

Revision ID: c5d7f9e3a1b2
Revises: b0e296cc4b17
Create Date: 2026-04-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c5d7f9e3a1b2"
down_revision: str | None = "afce66b11b80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add idempotency_key, trace_id, span_id columns to events table."""
    # Add new columns
    op.add_column("events", sa.Column("idempotency_key", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("trace_id", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("span_id", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("dataschema", sa.Text(), nullable=True))

    # Create unique index on idempotency_key (for deduplication)
    op.create_index(
        "idx_events_idempotency",
        "events",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # Create index on trace_id (for searching by trace)
    op.create_index(
        "idx_events_trace_id",
        "events",
        ["trace_id"],
        postgresql_where=sa.text("trace_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove idempotency_key, trace_id, span_id columns."""
    op.drop_index("idx_events_trace_id", table_name="events")
    op.drop_index("idx_events_idempotency", table_name="events")
    op.drop_column("events", "dataschema")
    op.drop_column("events", "span_id")
    op.drop_column("events", "trace_id")
    op.drop_column("events", "idempotency_key")
