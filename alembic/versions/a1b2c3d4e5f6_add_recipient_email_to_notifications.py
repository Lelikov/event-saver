"""add_recipient_email_to_notifications.

Revision ID: a1b2c3d4e5f6
Revises: 28bba7523965
Create Date: 2026-04-26 00:00:00.000000

Adds recipient_email (TEXT, nullable) to booking_email_notifications and
booking_telegram_notifications so that historical records preserve the email
address that was actually used at send time, regardless of future email changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "28bba7523965"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("booking_email_notifications", sa.Column("recipient_email", sa.Text(), nullable=True))
    op.add_column("booking_telegram_notifications", sa.Column("recipient_email", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("booking_telegram_notifications", "recipient_email")
    op.drop_column("booking_email_notifications", "recipient_email")
