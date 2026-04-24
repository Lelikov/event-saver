"""merge event_admin and lifecycle heads

Revision ID: 2af87f34c2ff
Revises: 28bba7523965, ca7326cf2ec5
Create Date: 2026-04-24 00:49:19.255727

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2af87f34c2ff'
down_revision: Union[str, Sequence[str], None] = ('28bba7523965', 'ca7326cf2ec5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
