"""merge recipient_email migration

Revision ID: 16939138e5a7
Revises: 2af87f34c2ff, a1b2c3d4e5f6
Create Date: 2026-04-27 02:11:57.031697

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16939138e5a7'
down_revision: Union[str, Sequence[str], None] = ('2af87f34c2ff', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
