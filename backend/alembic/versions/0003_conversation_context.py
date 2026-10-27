"""Хранение согласованных полей состояния agent-06.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_states", sa.Column(
        "shown", postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False,
    ))
    op.add_column("conversation_states", sa.Column("last_action", postgresql.JSONB()))
    op.add_column("conversation_states", sa.Column(
        "pending_skipped", sa.Boolean(), server_default=sa.text("false"), nullable=False,
    ))


def downgrade() -> None:
    op.drop_column("conversation_states", "pending_skipped")
    op.drop_column("conversation_states", "last_action")
    op.drop_column("conversation_states", "shown")
