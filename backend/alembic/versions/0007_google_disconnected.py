"""Google Календарь: отключение помнит календарь.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-29

calendar-01. Отключение больше не удаляет строку `google_connections`: токен стирается,
статус — `disconnected`, `calendar_id` остаётся. Повторное подключение пишет в тот же
календарь «Голосовой ассистент» — без второго календаря и копий событий.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_google_connections_status_values"


def upgrade() -> None:
    op.alter_column("google_connections", "refresh_token", existing_type=sa.Text(),
                    nullable=True)
    op.drop_constraint(op.f(CHECK), "google_connections", type_="check")
    op.create_check_constraint(op.f(CHECK), "google_connections",
                               "status IN ('connected', 'error', 'disconnected')")


def downgrade() -> None:
    op.execute("DELETE FROM google_connections WHERE status = 'disconnected'")
    op.drop_constraint(op.f(CHECK), "google_connections", type_="check")
    op.create_check_constraint(op.f(CHECK), "google_connections",
                               "status IN ('connected', 'error')")
    op.alter_column("google_connections", "refresh_token", existing_type=sa.Text(),
                    nullable=False)
