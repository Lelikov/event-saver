"""merge recipient_email migration.

Revision ID: 16939138e5a7
Revises: 2af87f34c2ff, a1b2c3d4e5f6
Create Date: 2026-04-27 02:11:57.031697

"""

from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "16939138e5a7"
down_revision: str | Sequence[str] | None = ("2af87f34c2ff", "a1b2c3d4e5f6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
