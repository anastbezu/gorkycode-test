"""Сервисы записей: создание и выборка за период (backend-02a).

Принимают и возвращают только Pydantic-модели контрактов (`CreateRecord`, `ListRecords`,
`ActionResult`, `Record`). ORM-модели `db.models` наружу не выходят.
Ошибки бизнес-правил возвращаются в `ActionResult(ok=False, error=...)`, без исключений:
агент передаёт текст ошибки LLM, API не отдаёт 500.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db import models
from schemas import ActionResult, CreateRecord, ListRecords, Record, RecordType


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _in_past(value: datetime, *, all_day: bool, now: datetime) -> bool:
    """Дата в прошлом? Для «весь день» сравниваем дни в поясе самой даты, а не моменты:
    «сегодня» без времени — не прошлое, даже если сейчас вечер.

    Для записей со временем — строго `value < now`, без запаса. Внимание: LLM считает время
    от момента запроса, а проверка идёт через секунды после него — «напомни сейчас» может
    быть отклонено как прошлое (см. docs/modules/backend.md).
    """
    if all_day:
        return value.date() < now.astimezone(value.tzinfo).date()
    return value < now


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

    all_day = not action.time_given
    for name in ("start", "deadline"):
        value = dates[name]
        if value is not None and _in_past(value, all_day=all_day, now=now):
            return _fail(f"Дата ({name}) уже в прошлом — нельзя создать запись на прошедшее время.")

    return None


def create_record(
    db: Session, user_id: UUID, action: CreateRecord, *, now: datetime | None = None
) -> ActionResult:
    """Создать задачу, встречу или напоминание.

    Время не названо (`time_given=False`): встреча не сохраняется (`missing=["start"]`,
    агент переспросит «На какое время?»), задача и напоминание сохраняются с `all_day=True`.
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
        # По постановке: время не названо — all_day = True (в т.ч. у задачи совсем без даты).
        all_day=not action.time_given,
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
    """Записи пользователя в интервале [date_from, date_to] по началу или по сроку.

    «Какие задачи на завтра» находит и задачи, у которых есть только срок.
    Сортировка — по началу, а если его нет — по сроку.
    """
    m = models.Record
    when = func.coalesce(m.start, m.deadline)
    query = (
        select(m)
        .where(m.user_id == user_id)
        .where(
            or_(
                m.start.between(action.date_from, action.date_to),
                m.deadline.between(action.date_from, action.date_to),
            )
        )
        .order_by(when, m.created_at)
    )
    if action.types:
        query = query.where(m.type.in_(action.types))

    rows = db.scalars(query).all()
    return ActionResult(
        action="list_records", ok=True, records=[Record.model_validate(r) for r in rows]
    )
