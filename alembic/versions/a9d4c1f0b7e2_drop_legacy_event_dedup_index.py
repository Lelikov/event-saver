"""Drop legacy (booking_id, event_type, source, hash) dedup index.

Deduplication is unified on the event_id primary key (broker redelivery)
and the partial unique index on idempotency_key (deterministic key set by
event-receiver). The legacy composite index mixed two incompatible hash
formulas (md5(payload::text) backfill vs application json.dumps formula),
treated NULLs as distinct, and crashed inserts that collided on the
non-targeted constraint. The hash column is kept as informational metadata.

Revision ID: a9d4c1f0b7e2
Revises: 16939138e5a7
Create Date: 2026-06-11 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op


revision: str = "a9d4c1f0b7e2"
down_revision: str | Sequence[str] | None = "16939138e5a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_events_booking_id_event_type_source_hash", table_name="events")


def downgrade() -> None:
    op.create_index(
        "uq_events_booking_id_event_type_source_hash",
        "events",
        ["booking_id", "event_type", "source", "hash"],
        unique=True,
    )
