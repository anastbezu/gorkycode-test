"""Google Календарь: подключение у учётки и состояние синхронизации записи.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29

calendar-01. `google_connections` — одно подключение на учётку (refresh-токен зашифрован,
id отдельного календаря «Голосовой ассистент»). `records.google_sync` — NULL / pending /
synced. Существующие записи не трогаются: в Google их отправит подключение.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_connections",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("calendar_id", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'connected'"), nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('connected', 'error')", name=op.f("ck_google_connections_status_values")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_google_connections_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_google_connections")),
    )
    op.add_column("records", sa.Column("google_sync", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        op.f("ck_records_google_sync_values"),
        "records",
        "google_sync IS NULL OR google_sync IN ('pending', 'synced')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_records_google_sync_values"), "records", type_="check")
    op.drop_column("records", "google_sync")
    op.drop_table("google_connections")
