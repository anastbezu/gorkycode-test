"""Подключение Google Календаря у учётки: состояние, начало, возврат от Google, отключение.

Сервисы синхронные и не коммитят — коммит в маршруте (`api/calendar.py`).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from db import models
from schemas import GoogleCalendarStatus

from . import google
from .config import CALENDAR_NAME, GoogleConfig
from .crypto import decrypt_token, encrypt_token
from .state import make_state, read_state

REVOKED_TEXT = "Доступ к Google Календарю отозван — переподключите."


class ConnectError(Exception):
    """Подключение не удалось — пользователь вернётся на `?calendar=error`."""


def pending_count(db: Session, user_id: UUID) -> int:
    return db.scalar(select(func.count()).select_from(models.Record).where(
        models.Record.user_id == user_id, models.Record.google_sync == "pending")) or 0


def active_connection(db: Session, user_id: UUID) -> models.GoogleConnection | None:
    """Подключение, которое работает или в ошибке; отключённое — как будто его нет."""
    row = db.get(models.GoogleConnection, user_id)
    return row if row is not None and row.status != "disconnected" else None


def connection_status(db: Session, user_id: UUID) -> GoogleCalendarStatus:
    row = active_connection(db, user_id)
    if row is None:
        return GoogleCalendarStatus(state="not_connected")
    return GoogleCalendarStatus(
        state="error" if row.status == "error" else "connected",
        email=row.email, error=row.error, pending=pending_count(db, user_id),
    )


def start_connect(config: GoogleConfig, user_id: UUID, now: datetime,
                  tz: str = "Europe/Moscow") -> str:
    return google.authorization_url(config, make_state(user_id, config.token_key, now, tz))


def finish_connect(db: Session, config: GoogleConfig, code: str, state: str,
                   now: datetime) -> tuple[UUID, str]:
    """Код от Google → токены → отдельный календарь → подключение. Возвращает учётку и пояс."""
    read = read_state(state, config.token_key, now)
    if read is None:
        raise ConnectError("state не сходится или истёк")
    user_id, tz = read
    user = db.get(models.User, user_id)
    if user is None or user.login is None:
        raise ConnectError("учётки нет")
    try:
        tokens = google.exchange_code(config, code)
        if not tokens.refresh_token:
            raise ConnectError("Google не выдал refresh-токен")
        row = db.get(models.GoogleConnection, user_id)
        calendar_id = row.calendar_id if row is not None else None
        if calendar_id is None:
            calendar_id = google.create_calendar(tokens.access_token, CALENDAR_NAME)
    except google.GoogleError as error:
        raise ConnectError(str(error)) from error

    if row is None:
        row = models.GoogleConnection(user_id=user_id, refresh_token="")
        db.add(row)
    row.email = tokens.email
    row.refresh_token = encrypt_token(tokens.refresh_token, config.token_key)
    row.calendar_id = calendar_id
    row.status = "connected"
    row.error = None
    db.flush()
    return user_id, tz


def disconnect(db: Session, config: GoogleConfig, user_id: UUID) -> None:
    """Отозвать доступ в Google и забыть токен и почту. События в Google остаются.

    `calendar_id` остаётся: повторное подключение пишет в тот же календарь, а не создаёт
    второй «Голосовой ассистент» с копиями событий. Найти его заново нельзя — список
    календарей разрешением `calendar.app.created` не читается."""
    row = active_connection(db, user_id)
    if row is None:
        return
    try:
        google.revoke(decrypt_token(row.refresh_token, config.token_key))
    except ValueError:
        pass  # ключ сменили — отозвать нечем, но забыть у нас всё равно нужно
    row.refresh_token = None
    row.email = None
    row.status = "disconnected"
    row.error = None
    db.execute(update(models.Record).where(models.Record.user_id == user_id)
               .values(google_sync=None))
    db.flush()


def mark_revoked(db: Session, user_id: UUID) -> None:
    """Google ответил invalid_grant: подключение в ошибке, ассистент работает без Google."""
    row = active_connection(db, user_id)
    if row is not None:
        row.status = "error"
        row.error = REVOKED_TEXT
        db.flush()
