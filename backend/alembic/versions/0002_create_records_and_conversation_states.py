"""Таблицы records и conversation_states.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25

Каркас сгенерирован `alembic revision --autogenerate` и вычищен руками:
типы колонок не ссылаются на код приложения, у всех ограничений стабильные имена.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPTZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("start_at", TIMESTAMPTZ, nullable=True),
        sa.Column("end_at", TIMESTAMPTZ, nullable=True),
        sa.Column("all_day", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deadline", TIMESTAMPTZ, nullable=True),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_records"),
        sa.CheckConstraint(
            "type IN ('task', 'meeting', 'reminder')", name=op.f("ck_records_record_type")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'done', 'cancelled')", name=op.f("ck_records_record_status")
        ),
        sa.CheckConstraint(
            "type <> 'meeting' OR start_at IS NOT NULL",
            name=op.f("ck_records_meeting_requires_start"),
        ),
        sa.CheckConstraint(
            "end_at IS NULL OR start_at IS NULL OR end_at > start_at",
            name=op.f("ck_records_end_after_start"),
        ),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_records_title_not_empty")),
    )
    op.create_index("ix_records_user_id_start_at", "records", ["user_id", "start_at"])
    op.create_index("ix_records_user_id_status", "records", ["user_id", "status"])

    op.create_table(
        "conversation_states",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("focus_record_id", sa.UUID(), nullable=True),
        sa.Column("pending", postgresql.JSONB(), nullable=True),
        sa.Column(
            "candidates",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "missing", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("awaiting", sa.String(16), nullable=True),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("conversation_id", name="pk_conversation_states"),
        sa.ForeignKeyConstraint(
            ["focus_record_id"],
            ["records.id"],
            name=op.f("fk_conversation_states_focus_record_id_records"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "awaiting IS NULL OR awaiting IN ('answer', 'choice')",
            name=op.f("ck_conversation_states_awaiting_values"),
        ),
    )
    op.create_index("ix_conversation_states_user_id", "conversation_states", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_states_user_id", table_name="conversation_states")
    op.drop_table("conversation_states")
    op.drop_index("ix_records_user_id_status", table_name="records")
    op.drop_index("ix_records_user_id_start_at", table_name="records")
    op.drop_table("records")
