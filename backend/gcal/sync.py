"""Синхронизация наших записей в Google Календарь (calendar-01).

Правда — в нашей базе. Изменённые записи помечаются «ждут» (`records.google_sync = pending`)
в той же транзакции, что и само изменение; отправка в Google — после коммита реплики,
отдельно: сбой или медленный Google не откатывает запись. Не ушло — запись остаётся «ждёт»
и уходит при следующем запросе пользователя.

Событие в Google — с id, равным нашему id записи: повтор не создаёт дубль.
"""

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from db import models
from schemas import ActionResult, RecordStatus, RecordType

from . import google
from .config import CALENDAR_NAME, GoogleConfig
from .connection import active_connection, mark_revoked
from .crypto import decrypt_token

# Длительность события, если у записи нет конца (наша запись времени конца не знает).
MEETING_MINUTES = 60  # как в проверке пересечений
REMINDER_MINUTES = 15
TASK_MINUTES = 30
FIRST_UPLOAD_DAYS = 14  # первая выгрузка при подключении — ближайшие 2 недели (контракт)
TURN_BUDGET_SECONDS = 3.0  # после реплики — не дольше 3 с, остальное догонит
MUTATIONS = {"create_record", "update_record", "set_status", "undo_last"}
NOT_SENT_TEXT = "В Google Календарь пока не ушло, повторю позже."


@dataclass
class SyncResult:
    sent: int = 0
    ok: bool = True  # False — Google не ответил или доступ отозван; что не ушло, ждёт


# --- какие записи отправлять ----------------------------------------------------------------

def changed_record_ids(result: ActionResult | None) -> list[UUID]:
    """Записи, которые реплика изменила: созданные, изменённые, откаченные."""
    if result is None:
        return []
    ids = [record.id for record in result.restored]
    if result.ok and result.action in MUTATIONS:
        ids += [record.id for record in result.records]
    return list(dict.fromkeys(ids))


def mark_pending(db: Session, user_id: UUID, record_ids: list[UUID]) -> int:
    """Пометить «ждут отправки» — только если у учётки подключён Google. Без коммита."""
    if not record_ids or active_connection(db, user_id) is None:
        return 0
    result = db.execute(
        update(models.Record)
        .where(models.Record.user_id == user_id, models.Record.id.in_(record_ids))
        .values(google_sync="pending")
    )
    return result.rowcount


def mark_first_upload(db: Session, user_id: UUID, now: datetime, tz: str) -> int:
    """При подключении — записи с датой в ближайшие 2 недели (датасет целиком не выгружаем)."""
    start = datetime.combine(now.astimezone(ZoneInfo(tz)).date(), datetime.min.time(),
                             ZoneInfo(tz))
    end = start + timedelta(days=FIRST_UPLOAD_DAYS)
    m = models.Record
    in_window = or_(
        (m.start >= start) & (m.start < end),
        m.start.is_(None) & (m.deadline >= start) & (m.deadline < end),
    )
    result = db.execute(
        update(m)
        .where(m.user_id == user_id, m.status != RecordStatus.CANCELLED, in_window)
        .values(google_sync="pending")
    )
    return result.rowcount


# --- как запись выглядит в Google -----------------------------------------------------------

def event_body(record: models.Record, tz: ZoneInfo) -> dict | None:
    """Событие Google для записи; `None` — у записи нет даты, в Google её нет."""
    title = record.title
    if record.status == RecordStatus.DONE:
        title = f"✓ {title}"
    if record.start is not None and not record.all_day:
        minutes = {RecordType.MEETING: MEETING_MINUTES, RecordType.REMINDER: REMINDER_MINUTES}
        end = record.end or record.start + timedelta(
            minutes=minutes.get(record.type, TASK_MINUTES))
        body: dict = {"start": {"dateTime": record.start.astimezone(tz).isoformat(),
                                "timeZone": tz.key},
                      "end": {"dateTime": end.astimezone(tz).isoformat(), "timeZone": tz.key}}
        if record.type == RecordType.REMINDER:
            body["reminders"] = {"useDefault": False,
                                 "overrides": [{"method": "popup", "minutes": 0}]}
    elif record.start is not None or record.deadline is not None:
        moment = record.start if record.start is not None else record.deadline
        day: date = moment.astimezone(tz).date()
        if record.start is None:
            title = f"Срок: {title}"
        body = {"start": {"date": day.isoformat()},
                "end": {"date": (day + timedelta(days=1)).isoformat()}}
    else:
        return None
    body.update(id=record.id.hex, summary=title, status="confirmed",
                description="Из «Голосового ассистента»")
    return body


# --- отправка -------------------------------------------------------------------------------

def _events_path(calendar_id: str, event_id: str | None = None) -> str:
    path = f"/calendars/{quote(calendar_id, safe='')}/events"
    return f"{path}/{event_id}" if event_id else path


def _push(record: models.Record, connection: models.GoogleConnection, access: str,
          tz: ZoneInfo) -> None:
    """Привести событие в Google к записи. Ошибка Google — исключение `GoogleError`."""
    timeout = google.SYNC_TIMEOUT
    event_id = record.id.hex
    body = event_body(record, tz)
    if record.status == RecordStatus.CANCELLED or body is None:
        response = google.calendar_request(
            "DELETE", _events_path(connection.calendar_id, event_id), access, timeout=timeout)
        if response.status_code not in (200, 204, 404, 410):
            raise google.GoogleError(f"событие не удалено: {response.status_code}")
        return
    # Обновить; «верни» после удаления восстанавливает событие (status = confirmed).
    response = google.calendar_request(
        "PUT", _events_path(connection.calendar_id, event_id), access, body, timeout)
    if response.status_code == 200:
        return
    if response.status_code != 404:
        raise google.GoogleError(f"событие не обновлено: {response.status_code}")
    response = google.calendar_request(
        "POST", _events_path(connection.calendar_id), access, body, timeout)
    if response.status_code == 404:
        # Календарь «Голосовой ассистент» удалили в Google — создаём заново.
        connection.calendar_id = google.create_calendar(access, CALENDAR_NAME, timeout)
        response = google.calendar_request(
            "POST", _events_path(connection.calendar_id), access, body, timeout)
    if response.status_code != 200:
        raise google.GoogleError(f"событие не создано: {response.status_code}")


def sync_pending(db: Session, config: GoogleConfig, user_id: UUID, tz: str, *,
                 limit: int = 50, budget: float | None = None) -> SyncResult:
    """Отправить «ждущие» записи учётки. Без коммита: коммитит вызывающий.

    `budget` — секунды: новые запросы после него не начинаются (остальное догонит потом).
    """
    connection = db.get(models.GoogleConnection, user_id)
    if connection is None or connection.status != "connected":
        return SyncResult()
    records = db.scalars(
        select(models.Record)
        .where(models.Record.user_id == user_id, models.Record.google_sync == "pending")
        .order_by(models.Record.updated_at)
        .limit(limit)
    ).all()
    if not records:
        return SyncResult()

    started = time.monotonic()
    result = SyncResult()
    zone = ZoneInfo(tz)
    try:
        access = google.refresh_access_token(
            config, decrypt_token(connection.refresh_token, config.token_key),
            google.SYNC_TIMEOUT)
        for record in records:
            if budget is not None and time.monotonic() - started > budget:
                result.ok = False
                break
            _push(record, connection, access, zone)
            dated = record.start is not None or record.deadline is not None
            record.google_sync = "synced" if dated else None
            result.sent += 1
    except google.GoogleAccessRevoked:
        mark_revoked(db, user_id)
        result.ok = False
    except (google.GoogleError, ValueError):  # ValueError — ключ шифрования не подходит
        result.ok = False
    db.flush()
    return result


def sync_after_turn(db: Session, user_id: UUID, tz: str) -> SyncResult | None:
    """После коммита реплики: отправить ждущие записи в пределах 3 с и закоммитить отметки.

    `None` — Google не подключён или ключей нет: ответу добавлять нечего.
    """
    from .config import google_config

    config = google_config()
    if config is None or active_connection(db, user_id) is None:
        return None
    result = sync_pending(db, config, user_id, tz, limit=10, budget=TURN_BUDGET_SECONDS)
    db.commit()
    return result
