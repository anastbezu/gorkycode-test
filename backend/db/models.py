"""ORM-модели хранилища (SQLAlchemy 2).

Контракт: docs/contracts/data-model.md — поля `Record` повторяют его один в один.
Служебные поля, которых нет в контракте (`updated_at`, `embedding`), живут только в БД.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    MetaData,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Размерность из DECOMPOSITION.md (text-embedding-3-small = 1536; gemini-embedding-001 тоже умеет 1536).
# TODO(Родион): подтвердить после выбора модели эмбеддингов.
EMBEDDING_DIM = 1536


class RecordType(StrEnum):
    TASK = "task"
    MEETING = "meeting"
    REMINDER = "reminder"


class RecordStatus(StrEnum):
    ACTIVE = "active"
    DONE = "done"
    CANCELLED = "cancelled"


# Единые имена ограничений и индексов — чтобы Alembic генерировал стабильные миграции.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Enum хранится как VARCHAR + CHECK (а не нативный тип Postgres): проще менять миграциями."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda e: [m.value for m in e],
    )


class Record(Base):
    """Задача, встреча или напоминание.

    Все даты — timestamptz: Postgres хранит их в UTC, в пояс пользователя переводим на выходе.
    """

    __tablename__ = "records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Анонимный идентификатор браузера; таблицы users нет (decisions.md).
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    type: Mapped[RecordType] = mapped_column(_enum(RecordType, "record_type"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)

    # В БД колонки называются start_at / end_at: `end` — зарезервированное слово SQL,
    # в сыром SQL его пришлось бы везде брать в кавычки. В Python имена как в контракте.
    start: Mapped[datetime | None] = mapped_column("start_at", DateTime(timezone=True))
    end: Mapped[datetime | None] = mapped_column("end_at", DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[RecordStatus] = mapped_column(
        _enum(RecordStatus, "record_status"),
        nullable=False,
        default=RecordStatus.ACTIVE,
        server_default=RecordStatus.ACTIVE.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # --- только в БД, не в контракте ---
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    # Вектор для поиска по смыслу (модуль Родиона). Пустой, пока не посчитан.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    __table_args__ = (
        # Те же правила, что в валидаторе Record.check_times из контракта.
        CheckConstraint(
            "type <> 'meeting' OR start_at IS NOT NULL",
            name="meeting_requires_start",
        ),
        CheckConstraint(
            "end_at IS NULL OR start_at IS NULL OR end_at > start_at",
            name="end_after_start",
        ),
        CheckConstraint("length(trim(title)) > 0", name="title_not_empty"),
    )

    def __repr__(self) -> str:
        return f"<Record {self.type} {self.title!r} start={self.start} status={self.status}>"
