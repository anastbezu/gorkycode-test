"""Таблица text_embeddings — векторы текстов для поиска по смыслу (search-01).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27

Вектор на текст, а не на запись (docs/modules/search.md): ключ — модель и md5 текста. Индекса по вектору
нет: у пользователя ~1000 записей, полный перебор быстрее индекса (README pgvector).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "text_embeddings",
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("text_hash", sa.String(32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(312), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("model", "text_hash", name="pk_text_embeddings"),
    )


def downgrade() -> None:
    op.drop_table("text_embeddings")
