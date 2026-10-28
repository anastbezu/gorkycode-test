"""Пользователи и вход: `users`, `auth_tokens`, момент отмены записи.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28

backend-04. Пользователи, которые уже есть в базе (по записям и разговорам), становятся
гостями с последним запросом «сейчас» — их данные проживут ещё 30 дней. У уже отменённых
записей момент отмены — `updated_at`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("login", sa.String(length=32), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(login IS NULL) = (password_hash IS NULL)", name=op.f("ck_users_account_has_password")
        ),
        sa.CheckConstraint(
            "NOT is_demo OR login IS NOT NULL", name=op.f("ck_users_demo_is_account")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index("uq_users_login_lower", "users", [sa.text("lower(login)")], unique=True)

    op.create_table(
        "auth_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_auth_tokens")),
    )
    op.create_index(op.f("ix_auth_tokens_user_id"), "auth_tokens", ["user_id"])

    op.add_column(
        "records", sa.Column("cancelled_at", postgresql.TIMESTAMP(timezone=True), nullable=True)
    )
    op.execute("UPDATE records SET cancelled_at = updated_at WHERE status = 'cancelled'")

    # Уже существующие пользователи — гости: без строки в users чистка их бы не нашла.
    op.execute(
        """
        INSERT INTO users (id)
        SELECT user_id FROM records
        UNION
        SELECT user_id FROM conversation_states
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_column("records", "cancelled_at")
    op.drop_index(op.f("ix_auth_tokens_user_id"), table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_index("uq_users_login_lower", table_name="users")
    op.drop_table("users")
