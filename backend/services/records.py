"""Сервисы записей: создание и выборка за период (backend-02a).

Принимают и возвращают только Pydantic-модели контрактов (`CreateRecord`, `ListRecords`,
`ActionResult`, `Record`). ORM-модели `db.models` наружу не выходят.
Ошибки бизнес-правил возвращаются в `ActionResult(ok=False, error=...)`, без исключений:
агент передаёт текст ошибки LLM, API не отдаёт 500.
"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db import models
from schemas import ActionResult, CreateRecord, ListRecords, Record, RecordStatus, RecordType

# Запас для проверки «в прошлом»: LLM считает время от момента запроса,
# а проверка идёт после ответа модели — «напомни через минуту» не должно отклоняться.
PAST_GRACE = timedelta(minutes=1)


def _is_all_day(action: CreateRecord) -> bool:
    """«Весь день» — назван день, но не время (контракт data-model). Без даты — не all_day."""
    return not action.time_given and action.start is not None


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _in_past(value: datetime, *, all_day: bool, now: datetime) -> bool:
    """Дата в прошлом? Для «весь день» сравниваем дни в поясе самой даты, а не моменты:
    «сегодня» без времени — не прошлое, даже если сейчас вечер.

    Для записей со временем — с запасом `PAST_GRACE`: время, которое LLM посчитала от момента
    запроса, к моменту проверки может уже на секунды отстать от `now`.
    """
    if all_day:
        return value.date() < now.astimezone(value.tzinfo).date()
    return value < now - PAST_GRACE


def _fail(error: str, *, missing: list[str] | None = None) -> ActionResult:
    return ActionResult(action="create_record", ok=False, error=error, missing=missing or [])


def validate_create(action: CreateRecord, now: datetime) -> ActionResult | None:
    """Бизнес-правила создания. `None` — всё в порядке, иначе — `ActionResult` с ошибкой.

    Чистая функция без базы: её же вызывает `create_record` до любого обращения к БД.
    """
    dates = {"start": action.start, "end": action.end, "deadline": action.deadline}
    for name, value in dates.items():
        if value is not None and not _is_aware(value):
            return _fail(f"Поле {name} должно содержать часовой пояс.")

    if action.type is RecordType.MEETING:
        if action.start is None:
            return _fail("Для встречи нужно время начала.", missing=["start"])
        if not action.time_given:
            return _fail("Не названо время встречи.", missing=["start"])

    if action.start is not None and action.end is not None and action.end <= action.start:
        return _fail("Время окончания должно быть позже времени начала.")

    all_day = _is_all_day(action)
    for name in ("start", "deadline"):
        value = dates[name]
        if value is not None and _in_past(value, all_day=all_day, now=now):
            return _fail(f"Дата ({name}) уже в прошлом — нельзя создать запись на прошедшее время.")

    return None


def create_record(
    db: Session, user_id: UUID, action: CreateRecord, *, now: datetime | None = None
) -> ActionResult:
    """Создать задачу, встречу или напоминание.

    Назван день без времени (`time_given=False`): встреча не сохраняется (`missing=["start"]`,
    агент переспросит «На какое время?»), задача и напоминание сохраняются с `all_day=True`.
    Запись без даты (`start=None`) — не `all_day`.
    """
    now = now or datetime.now().astimezone()
    if (error := validate_create(action, now)) is not None:
        return error

    row = models.Record(
        user_id=user_id,
        type=action.type,
        title=action.title.strip(),
        start=action.start,
        end=action.end,
        all_day=_is_all_day(action),
        deadline=action.deadline,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)  # подтянуть значения по умолчанию из базы: created_at, status
    except SQLAlchemyError:
        db.rollback()
        return _fail("Не удалось сохранить запись: проверьте поля и повторите.")

    return ActionResult(action="create_record", ok=True, records=[Record.model_validate(row)])


def list_records_for_period(db: Session, user_id: UUID, action: ListRecords) -> ActionResult:
    """Записи пользователя в интервале [date_from, date_to) по началу или по сроку.

    Правая граница не включается (контракт agent-tools): «сегодня» — до 00:00 завтра,
    и запись «на весь день» завтра (start = 00:00) в него не попадает.
    «Какие задачи на завтра» находит и задачи, у которых есть только срок.
    Отменённые (`cancelled`) не показываются. Сортировка — по началу, а если его нет — по сроку.
    """
    m = models.Record

    def in_period(column):
        return and_(column >= action.date_from, column < action.date_to)

    when = func.coalesce(m.start, m.deadline)
    query = (
        select(m)
        .where(m.user_id == user_id)
        .where(m.status != RecordStatus.CANCELLED)
        .where(or_(in_period(m.start), in_period(m.deadline)))
        .order_by(when, m.created_at)
    )
    if action.types:
        query = query.where(m.type.in_(action.types))

    rows = db.scalars(query).all()
    return ActionResult(
        action="list_records", ok=True, records=[Record.model_validate(r) for r in rows]
    )
