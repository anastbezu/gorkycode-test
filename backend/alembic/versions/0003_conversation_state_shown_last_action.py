"""Состояние разговора: показанный список, последнее действие, пропущенный черновик.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26

Поля `ConversationState` из контракта data-model.md (backend-03). У существующих строк
значения по умолчанию: пустой `shown`, без `last_action`, `pending_skipped = false`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_states",
        sa.Column(
            "shown", postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False
        ),
    )
    op.add_column(
        "conversation_states", sa.Column("last_action", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "conversation_states",
        sa.Column("pending_skipped", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("conversation_states", "pending_skipped")
    op.drop_column("conversation_states", "last_action")
    op.drop_column("conversation_states", "shown")
