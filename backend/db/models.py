"""ORM-модели хранилища (SQLAlchemy 2) — внутренняя деталь модуля `db`.

Наружу (агенту, API, поиску) отдаются только Pydantic-схемы из `schemas/`
(docs/contracts/data-model.md). Эти классы импортируют только сервисы бэкенда.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from schemas import RecordStatus, RecordType

# Единые имена ограничений — чтобы Alembic генерировал стабильные миграции.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class AwareDateTime(TypeDecorator):
    """`timestamptz`, который не принимает время без часового пояса.

    Postgres молча считает «наивное» время временем своего сервера — это тихая ошибка
    на несколько часов. Поэтому отклоняем его ещё до запроса в базу.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError(f"datetime без часового пояса не сохраняется: {value!r}")
        return value


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """VARCHAR + CHECK вместо нативного enum Postgres: проще менять миграциями."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda e: [m.value for m in e],
    )


class Record(Base):
    """Задача, встреча или напоминание. Поля — как `Record` в контракте.

    В БД колонки начала и конца называются `start_at` / `end_at`: `end` — зарезервированное
    слово SQL, в сыром SQL его пришлось бы всегда брать в кавычки. В Python — `start` / `end`.
    """

    __tablename__ = "records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[RecordType] = mapped_column(_enum(RecordType, "record_type"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    start: Mapped[datetime | None] = mapped_column("start_at", AwareDateTime())
    end: Mapped[datetime | None] = mapped_column("end_at", AwareDateTime())
    all_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    deadline: Mapped[datetime | None] = mapped_column(AwareDateTime())
    status: Mapped[RecordStatus] = mapped_column(
        _enum(RecordStatus, "record_status"),
        nullable=False,
        default=RecordStatus.ACTIVE,
        server_default=RecordStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Те же правила, что в валидаторе Record.check_times из контракта.
        CheckConstraint("type <> 'meeting' OR start_at IS NOT NULL", name="meeting_requires_start"),
        CheckConstraint(
            "end_at IS NULL OR start_at IS NULL OR end_at > start_at", name="end_after_start"
        ),
        CheckConstraint("length(trim(title)) > 0", name="title_not_empty"),
        # Списки «за период» и «активные» всегда в рамках одного пользователя.
        Index("ix_records_user_id_start_at", "user_id", "start_at"),
        Index("ix_records_user_id_status", "user_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Record {self.type} {self.title!r} start={self.start} status={self.status}>"


class ConversationState(Base):
    """Состояние разговора. Поля — как `ConversationState` в контракте.

    `pending` — черновик действия агента (`LLMAction`) в JSON; `candidates` и `missing` — массивы.
    """

    __tablename__ = "conversation_states"

    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    focus_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("records.id", ondelete="SET NULL")
    )
    pending: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    candidates: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'")
    )
    missing: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    awaiting: Mapped[str | None] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "awaiting IS NULL OR awaiting IN ('answer', 'choice')", name="awaiting_values"
        ),
    )
