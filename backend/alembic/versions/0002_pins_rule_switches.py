"""pinned conversations; email rules switch on/off instead of being soft-deleted

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('pinned', sa.Boolean(), nullable=False, server_default=sa.false()))
    # Until now "active = false" meant deleted; from here on it means switched off, and delete is real.
    op.execute("DELETE FROM email_rules WHERE active = false")


def downgrade() -> None:
    op.drop_column('conversations', 'pinned')
