"""add_user_id_to_participants.

Revision ID: f3a9b2c1d4e5
Revises: 89ec847d44a9
Create Date: 2026-04-16 00:00:00.000000

Aligns participants table with event-receiver message spec:
- user_id (UUID) from event-users service is now part of normalized participant data
- Unique key changed from (email) to (email, role) to match event-users uniqueness model
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "f3a9b2c1d4e5"
down_revision: str | Sequence[str] | None = "89ec847d44a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("participants", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))

    op.drop_constraint("uq_participants_email", "participants", type_="unique")
    op.drop_index("ix_participants_role", table_name="participants")

    op.create_unique_constraint("uq_participants_email_role", "participants", ["email", "role"])
    op.create_unique_constraint("uq_participants_user_id", "participants", ["user_id"])
    op.create_index("ix_participants_user_id", "participants", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_participants_user_id", table_name="participants")
    op.drop_constraint("uq_participants_user_id", "participants", type_="unique")
    op.drop_constraint("uq_participants_email_role", "participants", type_="unique")

    op.create_index("ix_participants_role", "participants", ["role"])
    op.create_unique_constraint("uq_participants_email", "participants", ["email"])

    op.drop_column("participants", "user_id")
