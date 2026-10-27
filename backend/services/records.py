"""Сервисы записей: создание, изменение, смена статуса, выборка за период (backend-02a, 03).

Принимают и возвращают только Pydantic-модели контрактов (`CreateRecord`, `UpdateRecord`,
`ListRecords`, `ActionResult`, `Record`). ORM-модели `db.models` наружу не выходят.
Ошибки бизнес-правил возвращаются в `ActionResult(ok=False, error=...)`, без исключений:
агент передаёт текст ошибки LLM, API не отдаёт 500.

Сервисы не делают `commit` — только `add` / `flush` в переданную сессию. Коммитит маршрут
`POST /api/chat` один раз за реплику (`docs/decisions.md`, «Доступ к БД»).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Interval, and_, func, literal, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db import models
from schemas import (
    ActionResult,
    CreateRecord,
    ListRecords,
    Record,
    RecordStatus,
    RecordType,
    UpdateRecord,
)

# Запас для проверки «в прошлом»: LLM считает время от момента запроса,
# а проверка идёт после ответа модели — «напомни через минуту» не должно отклоняться.
PAST_GRACE = timedelta(minutes=1)

# Встрече без конца для проверки пересечений даётся час (в запись не пишется).
DEFAULT_MEETING_DURATION = timedelta(minutes=60)

# Поля записи, которые меняет `update_record` (остальные поля `UpdateRecord` — про цель).
UPDATABLE_FIELDS = ("title", "start", "end", "time_given", "deadline")


@dataclass
class RecordChange:
    """Результат изменения записи: `ActionResult` и прежние значения для отката.

    `before` — прежние значения изменённых полей в JSON-виде (`{"start": "2026-10-22T15:00…"}`):
    агент кладёт его в `last_action.before`, «верни» передаёт эти значения обратно в тот же
    сервис. При ошибке `before` пустой.
    """

    result: ActionResult
    before: dict[str, Any] = field(default_factory=dict)


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


def _fail(action: str, error: str, *, missing: list[str] | None = None) -> ActionResult:
    return ActionResult(action=action, ok=False, error=error, missing=missing or [])


def _check_dates(
    action_name: str,
    *,
    record_type: RecordType,
    start: datetime | None,
    end: datetime | None,
    deadline: datetime | None,
    all_day: bool,
    time_given: bool,
    check_past: dict[str, datetime | None],
    now: datetime,
) -> ActionResult | None:
    """Общие правила дат для создания и изменения. `None` — всё в порядке."""
    for name, value in {"start": start, "end": end, "deadline": deadline}.items():
        if value is not None and not _is_aware(value):
            return _fail(action_name, f"Поле {name} должно содержать часовой пояс.")

    if record_type is RecordType.MEETING:
        if start is None:
            return _fail(action_name, "Для встречи нужно время начала.", missing=["start"])
        if not time_given:
            return _fail(action_name, "Не названо время встречи.", missing=["start"])

    if start is not None and end is not None and end <= start:
        return _fail(action_name, "Время окончания должно быть позже времени начала.")

    for name, value in check_past.items():
        if value is not None and _in_past(value, all_day=all_day, now=now):
            return _fail(
                action_name,
                f"Дата ({name}) уже в прошлом — нельзя поставить запись на прошедшее время.",
            )
    return None


def validate_create(action: CreateRecord, now: datetime) -> ActionResult | None:
    """Бизнес-правила создания. `None` — всё в порядке, иначе — `ActionResult` с ошибкой.

    Чистая функция без базы: её же вызывает `create_record` до любого обращения к БД.
    """
    return _check_dates(
        "create_record",
        record_type=action.type,
        start=action.start,
        end=action.end,
        deadline=action.deadline,
        all_day=_is_all_day(action),
        time_given=action.time_given,
        check_past={"start": action.start, "deadline": action.deadline},
        now=now,
    )


# --- конфликт и дубль --------------------------------------------------------------------


def _meeting_end(start: datetime, end: datetime | None) -> datetime:
    return end if end is not None else start + DEFAULT_MEETING_DURATION


def find_conflicts(
    db: Session,
    user_id: UUID,
    start: datetime,
    end: datetime | None,
    *,
    exclude_id: UUID | None = None,
) -> list[Record]:
    """Активные встречи пользователя, пересекающиеся с интервалом [start, end).

    У встреч без конца — 60 минут от начала (и у проверяемой, и у найденных).
    Встречи «на весь день» не участвуют. `exclude_id` — сама переносимая запись.
    """
    m = models.Record
    new_end = _meeting_end(start, end)
    hour = literal(DEFAULT_MEETING_DURATION, type_=Interval())
    other_end = func.coalesce(m.end, m.start + hour)
    query = (
        select(m)
        .where(
            m.user_id == user_id,
            m.type == RecordType.MEETING,
            m.status == RecordStatus.ACTIVE,
            m.all_day.is_(False),
            m.start.is_not(None),
            m.start < new_end,
            other_end > start,
        )
        .order_by(m.start)
    )
    if exclude_id is not None:
        query = query.where(m.id != exclude_id)
    return [Record.model_validate(r) for r in db.scalars(query).all()]


def find_duplicate(db: Session, user_id: UUID, title: str, start: datetime) -> Record | None:
    """Точный дубль: активная запись с тем же названием (без учёта регистра) и тем же началом."""
    m = models.Record
    row = db.scalar(
        select(m)
        .where(
            m.user_id == user_id,
            m.status == RecordStatus.ACTIVE,
            # Обе стороны — через lower() базы: один и тот же регистр при любой локали.
            func.lower(m.title) == func.lower(title.strip()),
            m.start == start,
        )
        .limit(1)
    )
    return Record.model_validate(row) if row is not None else None


def _conflicts_for(db: Session, row: models.Record) -> list[Record]:
    """Пересечения для встречи со временем; для остального — пусто."""
    if row.type is not RecordType.MEETING or row.all_day or row.start is None:
        return []
    return find_conflicts(db, row.user_id, row.start, row.end, exclude_id=row.id)


def _save(db: Session, row: models.Record, changes: dict[str, Any] | None = None) -> bool:
    """`flush` записи в точке сохранения: при ошибке откатывается только она,
    а транзакция реплики (и всё, что в ней уже сделано) остаётся целой.

    Новые значения полей (`changes`) ставятся уже внутри точки сохранения: `begin_nested`
    сначала сбрасывает в базу всё, что накопилось в сессии, и ошибка изменённой заранее записи
    пришлась бы на транзакцию реплики — дальше сессия не дала бы сохранить даже состояние.
    При откате точки сохранения SQLAlchemy перечитывает запись из базы — новые значения не
    остаются в памяти."""
    try:
        with db.begin_nested():
            db.add(row)
            for name, value in (changes or {}).items():
                setattr(row, name, value)
            db.flush()
        db.refresh(row)  # значения по умолчанию из базы: created_at, updated_at, status
    except SQLAlchemyError:
        return False
    return True


# --- создание -----------------------------------------------------------------------------


def create_record(
    db: Session, user_id: UUID, action: CreateRecord, *, now: datetime | None = None
) -> ActionResult:
    """Создать задачу, встречу или напоминание.

    Назван день без времени (`time_given=False`): встреча не сохраняется (`missing=["start"]`,
    агент переспросит «На какое время?»), задача и напоминание сохраняются с `all_day=True`.
    Запись без даты (`start=None`) — не `all_day`.
    Точный дубль (то же название и начало у активной записи) не создаётся: `ok=False`,
    существующая запись — в `records`. Встреча, пересекающаяся с другими, создаётся,
    пересечения — в `conflicts`.
    """
    now = now or datetime.now().astimezone()
    if (error := validate_create(action, now)) is not None:
        return error

    title = action.title.strip()
    if action.start is not None and (dup := find_duplicate(db, user_id, title, action.start)):
        return ActionResult(
            action="create_record",
            ok=False,
            error="Такая запись уже есть — второй раз не создаю.",
            records=[dup],
        )

    row = models.Record(
        user_id=user_id,
        type=action.type,
        title=title,
        start=action.start,
        end=action.end,
        all_day=_is_all_day(action),
        deadline=action.deadline,
    )
    if not _save(db, row):
        return _fail("create_record", "Не удалось сохранить запись: проверьте поля и повторите.")

    return ActionResult(
        action="create_record",
        ok=True,
        records=[Record.model_validate(row)],
        conflicts=_conflicts_for(db, row),
    )


# --- изменение и статус -------------------------------------------------------------------


def _user_record(db: Session, user_id: UUID, record_id: UUID) -> models.Record | None:
    return db.scalar(
        select(models.Record).where(models.Record.id == record_id, models.Record.user_id == user_id)
    )


def _json(value: Any, tz) -> Any:
    """Значение для `before` в JSON-виде; даты — в поясе пользователя (`tz`), а не базы."""
    if isinstance(value, datetime):
        return (value.astimezone(tz) if tz is not None else value).isoformat()
    return value


def update_record(
    db: Session,
    user_id: UUID,
    record_id: UUID,
    action: UpdateRecord,
    *,
    now: datetime | None = None,
) -> RecordChange:
    """Изменить запись пользователя: только поля, переданные в `action` (не `None`).

    - Меняются `title`, `start`, `end`, `time_given`, `deadline`; цель (`target`) и
      `replaces_last` здесь не используются — запись уже найдена агентом (`record_id`).
    - `time_given=False` при новом `start` — запись «на весь день», как при создании;
      `time_given` не передан — «весь день» остаётся прежним.
    - У встречи с концом перенос начала без нового конца сдвигает конец на ту же величину:
      длительность сохраняется (иначе конец оказался бы раньше начала).
    - Проверки — как при создании: пояс, конец позже начала, новая дата не в прошлом.
    - Возвращает изменённую запись (и пересечения, если это встреча) и прежние значения
      изменённых полей в `RecordChange.before`. Откат («верни») — `restore_record` с этим
      `before`: в `UpdateRecord` `None` значит «не менять», и пустое поле им не вернуть.
    """
    now = now or datetime.now().astimezone()
    row = _user_record(db, user_id, record_id)
    if row is None:
        return RecordChange(_fail("update_record", "Запись не найдена."))

    changes = {
        name: getattr(action, name)
        for name in UPDATABLE_FIELDS
        if getattr(action, name) is not None
    }
    if not changes:
        return RecordChange(_fail("update_record", "Не сказано, что изменить."))

    start = changes.get("start", row.start)
    end = changes.get("end", row.end)
    if "start" in changes and "end" not in changes and row.end is not None and row.start:
        end = row.end + (start - row.start)  # сохранить длительность встречи
    deadline = changes.get("deadline", row.deadline)

    if "time_given" in changes or "start" in changes:
        time_given = changes.get("time_given", not row.all_day)
    else:
        time_given = not row.all_day
    all_day = start is not None and not time_given

    check_past = {
        name: value for name, value in (("start", start), ("deadline", deadline))
        if name in changes
    }
    error = _check_dates(
        "update_record",
        record_type=row.type,
        start=start,
        end=end,
        deadline=deadline,
        all_day=all_day,
        time_given=time_given or start is None,
        check_past=check_past,
        now=now,
    )
    if error is not None:
        return RecordChange(error)

    # Пояс пользователя — из новых дат запроса (база отдаёт время в своём поясе).
    user_tz = next(
        (v.tzinfo for v in (action.start, action.end, action.deadline) if v is not None), None
    )
    title = changes["title"].strip() if "title" in changes else row.title
    return _apply(db, row, title, start, end, deadline, all_day, user_tz)


def restore_record(
    db: Session, user_id: UUID, record_id: UUID, before: dict[str, Any]
) -> RecordChange:
    """Откатить изменение («верни»): вернуть полям значения из `before` `update_record`.

    - `None` в `before` — тоже значение: поле было пустым и снова станет пустым
      («поставь задаче срок на пятницу» → «верни» убирает срок).
    - Даты — строки ISO 8601, как их пишет `update_record`; «весь день» — через `time_given`.
    - Проверки — пояс и конец позже начала; «не в прошлом» не проверяется: прежнее время
      могло уже пройти, а откат должен вернуть запись как была.
    - Возвращает запись и `before` самого отката (повторное «верни» не нужно, но формат общий).
    """
    row = _user_record(db, user_id, record_id)
    if row is None:
        return RecordChange(_fail("update_record", "Запись не найдена."))
    unknown = set(before) - {"title", "start", "end", "deadline", "time_given"}
    if unknown:
        return RecordChange(_fail("update_record", f"Нельзя вернуть поля: {sorted(unknown)}."))

    try:
        dates = {
            name: datetime.fromisoformat(before[name]) if before[name] is not None else None
            for name in ("start", "end", "deadline")
            if name in before
        }
    except (TypeError, ValueError):
        return RecordChange(_fail("update_record", "Прежние значения записи повреждены."))
    start = dates.get("start", row.start)
    end = dates.get("end", row.end)
    deadline = dates.get("deadline", row.deadline)
    all_day = not before["time_given"] if "time_given" in before else row.all_day
    all_day = all_day and start is not None  # без даты — не «весь день»

    error = _check_dates(
        "update_record",
        record_type=row.type,
        start=start,
        end=end,
        deadline=deadline,
        all_day=all_day,
        time_given=not all_day,
        check_past={},
        now=datetime.now().astimezone(),
    )
    if error is not None:
        return RecordChange(error)

    user_tz = next((v.tzinfo for v in dates.values() if v is not None), None)
    title = before["title"] if before.get("title") is not None else row.title
    return _apply(db, row, title, start, end, deadline, all_day, user_tz)


def _apply(
    db: Session,
    row: models.Record,
    title: str,
    start: datetime | None,
    end: datetime | None,
    deadline: datetime | None,
    all_day: bool,
    user_tz,
) -> RecordChange:
    """Записать новые значения полей; в `before` — прежние значения изменённых полей."""
    new_values = {"title": title, "start": start, "end": end, "deadline": deadline,
                  "all_day": all_day}
    changed = {name: value for name, value in new_values.items() if getattr(row, name) != value}
    before: dict[str, Any] = {name: _json(getattr(row, name), user_tz) for name in changed}
    # В `before` «весь день» выражается так же, как в `UpdateRecord`, — через `time_given`.
    if "all_day" in before:
        before["time_given"] = not before.pop("all_day")

    if not _save(db, row, changed):
        return RecordChange(_fail("update_record", "Не удалось сохранить изменения."))

    return RecordChange(
        ActionResult(
            action="update_record",
            ok=True,
            records=[Record.model_validate(row)],
            conflicts=_conflicts_for(db, row),
        ),
        before,
    )


def set_status(
    db: Session, user_id: UUID, record_id: UUID, status: RecordStatus
) -> RecordChange:
    """Отметить выполненной (`done`), отменить (`cancelled`) или вернуть в активные (`active`).

    Отменённая запись не удаляется — её можно вернуть. Прежний статус — в `before`
    (`{"status": "active"}`): откат — тот же сервис с прежним статусом.
    """
    row = _user_record(db, user_id, record_id)
    if row is None:
        return RecordChange(_fail("set_status", "Запись не найдена."))

    before = {"status": row.status.value} if row.status != status else {}
    if not _save(db, row, {"status": status}):
        return RecordChange(_fail("set_status", "Не удалось изменить статус."))

    return RecordChange(
        ActionResult(action="set_status", ok=True, records=[Record.model_validate(row)]), before
    )


# --- выборка ------------------------------------------------------------------------------


def list_records_for_period(db: Session, user_id: UUID, action: ListRecords) -> ActionResult:
    """Записи пользователя в интервале [date_from, date_to) по началу или по сроку.

    Правая граница не включается (контракт agent-tools): «сегодня» — до 00:00 завтра,
    и запись «на весь день» завтра (start = 00:00) в него не попадает.
    Без date_to верхней границы нет; активные записи без даты добавляются в конец.
    «Какие задачи на завтра» находит и задачи, у которых есть только срок.
    Отменённые (`cancelled`) не показываются. Сортировка — по началу, а если его нет — по сроку.
    """
    m = models.Record

    def in_period(column):
        if action.date_to is None:
            return column >= action.date_from
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
    records = [Record.model_validate(r) for r in rows]
    if action.date_to is None:
        records.extend(list_undated_records(db, user_id, action.types))
    return ActionResult(action="list_records", ok=True, records=records)


def list_undated_records(
    db: Session, user_id: UUID, types: list[RecordType] | None = None
) -> list[Record]:
    """Активные записи пользователя без даты — нет ни начала, ни срока («прочитать книгу»).

    В список за период они не попадают; панель «Мои дела» показывает их отдельным блоком
    «Без срока» (FEATURES P1 №14). Выполненные и отменённые не показываются.
    Сортировка — по времени создания.
    """
    m = models.Record
    query = (
        select(m)
        .where(m.user_id == user_id)
        .where(m.status == RecordStatus.ACTIVE)
        .where(m.start.is_(None), m.deadline.is_(None))
        .order_by(m.created_at)
    )
    if types:
        query = query.where(m.type.in_(types))
    return [Record.model_validate(r) for r in db.scalars(query).all()]


def get_record(db: Session, user_id: UUID, record_id: UUID) -> Record | None:
    """Запись в фокусе: чужие и удалённые записи не возвращаются агенту."""
    row = _user_record(db, user_id, record_id)
    return Record.model_validate(row) if row is not None else None
