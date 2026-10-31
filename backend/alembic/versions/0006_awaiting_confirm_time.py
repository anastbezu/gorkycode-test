"""Состояние разговора: `awaiting` принимает «confirm» и «time» (agent-10).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29

Быстрые ответы (api.md, «Правила»): сервер говорит, чего ждёт, — выбора (`choice`),
подтверждения массового действия (`confirm`), времени встречи (`time`) или ответа (`answer`).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_conversation_states_awaiting_values"
TABLE = "conversation_states"


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT),
        TABLE,
        "awaiting IS NULL OR awaiting IN ('answer', 'choice', 'confirm', 'time')",
    )


def downgrade() -> None:
    # Новые значения прежнее ограничение не примет: такие ожидания снимаются — разговор просто
    # перестаёт ждать ответа, записи не меняются.
    op.execute(f"UPDATE {TABLE} SET awaiting = NULL WHERE awaiting IN ('confirm', 'time')")
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT), TABLE, "awaiting IS NULL OR awaiting IN ('answer', 'choice')"
    )
