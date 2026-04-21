"""merge event_admin and main heads.

Revision ID: 89ec847d44a9
Revises: c5d7f9e3a1b2, ea_0001
Create Date: 2026-04-16 15:19:56.111570

"""

from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "89ec847d44a9"
down_revision: str | Sequence[str] | None = ("c5d7f9e3a1b2", "ea_0001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
