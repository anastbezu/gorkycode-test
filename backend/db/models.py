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
    # Когда запись отменили; пусто, если она не отменена. По нему чистка удаляет записи,
    # отменённые больше 30 дней назад: `updated_at` не годится — меняется при любой правке.
    cancelled_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    # Синхронизация с Google Календарём (calendar-01): NULL — не отправлялась (нет подключения
    # или записи без даты), «pending» — ждёт отправки, «synced» — в Google как у нас.
    google_sync: Mapped[str | None] = mapped_column(String(16))
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
        CheckConstraint(
            "google_sync IS NULL OR google_sync IN ('pending', 'synced')",
            name="google_sync_values",
        ),
    )

    def __repr__(self) -> str:
        return f"<Record {self.type} {self.title!r} start={self.start} status={self.status}>"


class ConversationState(Base):
    """Состояние разговора. Поля — как `ConversationState` в контракте.

    `pending` и `last_action` — JSON; `shown`, `candidates` и `missing` — массивы.
    """

    __tablename__ = "conversation_states"

    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    focus_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("records.id", ondelete="SET NULL")
    )
    # Записи, показанные пользователю под номерами: номер N — shown[N - 1].
    shown: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'")
    )
    # Последнее изменяющее действие (`LastAction`) — для поправки, отката и замены цели.
    last_action: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pending: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Прошлая реплика была не про черновик — следующая такая сбрасывает черновик.
    pending_skipped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
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


class User(Base):
    """Пользователь: гость или учётка.

    Гость — строка без логина: создаётся при первом запросе с новым `X-User-Id`.
    Учётка — с логином и хешем пароля (argon2). `id` — тот же `user_id`, что у записей и
    разговоров. Внешних ключей от записей сюда нет: записи гостя удаляет чистка
    (`services/retention.py`), а не каскад.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    login: Mapped[str | None] = mapped_column(String(32))
    password_hash: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), nullable=False, server_default=func.now()
    )
    # Последний запрос гостя (обновляется не чаще раза в час) — для чистки через 30 дней.
    last_seen_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("(login IS NULL) = (password_hash IS NULL)", name="account_has_password"),
        CheckConstraint("NOT is_demo OR login IS NOT NULL", name="demo_is_account"),
        # Логин уникален без учёта регистра.
        Index("uq_users_login_lower", func.lower(text("login")), unique=True),
    )


class AuthToken(Base):
    """Токен входа. Хранится SHA-256 токена, сам токен знает только клиент.

    Выход — удаление строки: после него токен не принимается.
    """

    __tablename__ = "auth_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)


class GoogleConnection(Base):
    """Подключение Google Календаря у учётки (calendar-01).

    Refresh-токен хранится зашифрованным (`gcal/crypto.py`, ключ `GOOGLE_TOKEN_KEY`):
    в браузер и в логи не попадает. `calendar_id` — отдельный календарь «Голосовой ассистент»,
    который приложение создаёт в Google пользователя (разрешение `calendar.app.created`).
    Удаление учётки удаляет и подключение.
    """

    __tablename__ = "google_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    email: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)  # зашифрован
    calendar_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="connected", server_default=text("'connected'")
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("status IN ('connected', 'error')", name="status_values"),
    )
