"""Изменение записей: update_record, set_status, undo_last, replaces_last (agent-07).

Цель находит `targets.resolve_target`, меняют сервисы записей (backend-03). Здесь — порядок:
откат для `replaces_last`, поиск цели, исполнение над одной или несколькими записями,
прежние значения для `last_action.before`. Состояние меняет только `update_state`.
"""

from asyncio import to_thread
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from schemas import (
    ActionResult,
    ConversationState,
    LastAction,
    Record,
    RecordStatus,
    SetStatus,
    UndoLast,
    UpdateRecord,
)
from services.records import get_record, restore_record, set_status, update_record

from .targets import resolve_target

CHANGE_ACTIONS = {"update_record", "set_status", "undo_last"}
NOTHING_TO_UNDO = "Нечего возвращать."


@dataclass
class ChangeOutcome:
    """Результат для ответа и состояния; `before` — в порядке `result.records`."""

    result: ActionResult
    before: list[dict[str, Any]] = field(default_factory=list)
    similar: bool = False  # кандидаты только похожи: «Точно такой нет. Может, эту?»
    confirm: bool = False  # несколько записей одной командой: «Отменить 3 …?»
    # Действие, которое на самом деле обработано: со статусом прошлого действия при
    # replaces_last, со временем записи после keep_time. Его получают ответ и update_state.
    applied: UpdateRecord | SetStatus | None = None


def changes_nothing(action: UpdateRecord) -> bool:
    return all(
        getattr(action, name) is None
        for name in ("title", "start", "end", "deadline", "time_given", "shift_minutes")
    )


def apply_shift(action: UpdateRecord, record: Record) -> UpdateRecord:
    """«На час позже»: модель передаёт только сдвиг (`shift_minutes`), новое время от
    текущего времени записи считает код — модели не нужно видеть запись (один вызов LLM).
    Конец встречи сдвигает сервис update_record (длительность сохраняется)."""
    if not action.shift_minutes:
        return action.model_copy(update={"shift_minutes": None})
    delta = timedelta(minutes=action.shift_minutes)
    update: dict[str, Any] = {"shift_minutes": None}
    if record.start is not None:
        update["start"] = record.start + delta
        update["time_given"] = not record.all_day
    elif record.deadline is not None:
        update["deadline"] = record.deadline + delta
    return action.model_copy(update=update)


def keep_time(action: UpdateRecord, record: Record, zone: ZoneInfo) -> UpdateRecord:
    """«Перенеси на пятницу»: модель прислала только день (полночь без time_given) —
    время остаётся прежним, как требует контракт update_record."""
    if action.start is None or action.time_given or record.start is None or record.all_day:
        return action
    day = action.start.astimezone(zone)
    if (day.hour, day.minute) != (0, 0):
        return action
    old = record.start.astimezone(zone)
    start = day.replace(hour=old.hour, minute=old.minute)
    end = action.end
    if end is None and record.end is not None:
        end = start + (record.end - record.start)  # длительность встречи сохраняется
    return action.model_copy(update={"start": start, "end": end, "time_given": True})


def confirming(state: ConversationState, action: UpdateRecord | SetStatus) -> list[UUID] | None:
    """Кандидаты, если это ответ на «Отменить N записей?» тем же массовым действием."""
    pending = state.pending.root if state.pending is not None else None
    same = (
        state.awaiting == "choice" and state.candidates
        and isinstance(action, SetStatus) and action.target.all
        and isinstance(pending, SetStatus) and pending.target.all
        and pending.status == action.status
    )
    return list(state.candidates) if same else None


def target_statuses(action: UpdateRecord | SetStatus) -> list[RecordStatus]:
    """Среди каких записей искать: «верни в активные», «не выполнено» — среди закрытых."""
    if isinstance(action, SetStatus) and action.status == RecordStatus.ACTIVE:
        return [RecordStatus.DONE, RecordStatus.CANCELLED]
    return [RecordStatus.ACTIVE]


async def undo(db, user_id: UUID, last: LastAction) -> tuple[list[Record], str | None]:
    """Откатить `last_action`: изменение — прежними значениями, статус — прежним статусом,
    создание — отменой созданной записи. Возвращает откаченные записи или ошибку."""
    restored: list[Record] = []
    befores = list(last.before) + [{}] * (len(last.record_ids) - len(last.before))
    for record_id, before in zip(last.record_ids, befores, strict=True):
        if last.action == "create_record":
            change = await to_thread(set_status, db, user_id, record_id, RecordStatus.CANCELLED)
        elif last.action == "update_record":
            change = await to_thread(restore_record, db, user_id, record_id, before)
        elif "status" in before:
            change = await to_thread(
                set_status, db, user_id, record_id, RecordStatus(before["status"])
            )
        else:
            change = None  # статус не менялся — возвращать нечего, запись та же
        if change is not None and not change.result.ok:
            return restored, change.result.error or "Не удалось вернуть."
        if change is not None:
            restored.extend(change.result.records)
    return restored, None


class MassChangeError(RuntimeError):
    """Массовое изменение не удалось ни довести, ни вернуть. Исключение уходит в маршрут
    `/api/chat`, и тот откатывает всю транзакцию реплики — частичный результат не коммитится."""


async def _revert(
    db, user_id: UUID, action: UpdateRecord | SetStatus, changed: list[Record],
    befores: list[dict[str, Any]],
) -> None:
    """Вернуть уже изменённые записи прежними значениями (если нет точки сохранения)."""
    for record, before in zip(changed, befores, strict=True):
        if isinstance(action, UpdateRecord):
            change = await to_thread(restore_record, db, user_id, record.id, before)
        elif "status" in before:
            change = await to_thread(
                set_status, db, user_id, record.id, RecordStatus(before["status"])
            )
        else:
            continue  # статус не менялся
        if not change.result.ok:
            raise MassChangeError(
                f"Не удалось вернуть запись {record.id} после ошибки массового изменения: "
                f"{change.result.error}"
            )


async def _savepoint(db, records: list[Record]):
    """Точка сохранения на массовое изменение: при ошибке откатывается вся операция разом."""
    if len(records) < 2 or not hasattr(db, "begin_nested"):
        return None
    return await to_thread(db.begin_nested)


async def _apply(
    db, user_id: UUID, action: UpdateRecord | SetStatus, records: list[Record], now: datetime
) -> ChangeOutcome:
    changed: list[Record] = []
    conflicts: list[Record] = []
    befores: list[dict[str, Any]] = []
    applied = action
    savepoint = await _savepoint(db, records)
    for record in records:
        if isinstance(action, UpdateRecord):
            applied = keep_time(apply_shift(action, record), record, now.tzinfo)
            change = await to_thread(update_record, db, user_id, record.id, applied, now=now)
        else:
            change = await to_thread(set_status, db, user_id, record.id, action.status)
        if not change.result.ok:
            # Массовое действие — всё или ничего: иначе маршрут закоммитит часть изменений
            # без last_action, и «верни» их не откатит. Не получилось вернуть — исключение,
            # и маршрут откатит транзакцию реплики целиком.
            if savepoint is not None:
                await to_thread(savepoint.rollback)
            else:
                await _revert(db, user_id, action, changed, befores)
            return ChangeOutcome(change.result, applied=applied)
        changed.extend(change.result.records)
        conflicts.extend(change.result.conflicts)
        befores.append(change.before)
    if savepoint is not None:
        await to_thread(savepoint.commit)
    result = ActionResult(action=action.action, ok=True, records=changed, conflicts=conflicts)
    return ChangeOutcome(result, befores, applied=applied)


async def execute_change(
    db,
    user_id: UUID,
    action: UpdateRecord | SetStatus | UndoLast,
    state: ConversationState,
    *,
    now: datetime,
) -> ChangeOutcome:
    if isinstance(action, UndoLast):
        if state.last_action is None:
            return ChangeOutcome(ActionResult(action="undo_last", ok=False, error=NOTHING_TO_UNDO))
        restored, error = await undo(db, user_id, state.last_action)
        if error is not None:
            return ChangeOutcome(ActionResult(action="undo_last", ok=False, error=error))
        return ChangeOutcome(ActionResult(action="undo_last", ok=True, restored=restored))

    restored: list[Record] = []
    if (isinstance(action, SetStatus) and action.replaces_last and state.last_action is not None
            and state.last_action.action == "set_status" and state.last_action.record_ids):
        # «Нет, не этот, а тот»: тот же статус, что применили к прошлой записи, — модель
        # иногда путает его с «верни» (active).
        previous = await to_thread(get_record, db, user_id, state.last_action.record_ids[0])
        if previous is not None:
            action = action.model_copy(update={"status": previous.status})
    if action.replaces_last and state.last_action is not None:
        # «Нет, не этот, а тот»: сначала вернуть прошлое, потом то же действие с новой целью.
        restored, error = await undo(db, user_id, state.last_action)
        if error is not None:
            return ChangeOutcome(ActionResult(action=action.action, ok=False, error=error),
                                 applied=action)

    if isinstance(action, UpdateRecord) and action.target.all:
        result = ActionResult(
            action=action.action, ok=False, restored=restored,
            error="Изменить несколько записей сразу не получится — назовите одну.",
        )
        return ChangeOutcome(result, applied=action)

    target = await resolve_target(db, user_id, action.target, state, target_statuses(action),
                                  confirming=confirming(state, action))
    if target.error is not None:
        result = ActionResult(
            action=action.action, ok=False, error=target.error, restored=restored
        )
        return ChangeOutcome(result, applied=action)
    if target.candidates:
        # Ничего не меняем до выбора: кандидаты станут номерами на экране, а в черновик
        # (pending) уйдёт исправленное действие.
        result = ActionResult(
            action=action.action, ok=False, candidates=target.candidates, restored=restored
        )
        return ChangeOutcome(result, similar=target.similar, confirm=target.confirm,
                             applied=action)

    if isinstance(action, UpdateRecord) and changes_nothing(action):
        result = ActionResult(action=action.action, ok=False, restored=restored,
                              error="Что изменить у этой записи? Назовите новое время или дату.")
        return ChangeOutcome(result, applied=action)
    if isinstance(action, UpdateRecord) and action.shift_minutes and any(
            r.start is None and r.deadline is None for r in target.records):
        result = ActionResult(action=action.action, ok=False, restored=restored,
                              error="У записи нет времени — назовите новую дату или время.")
        return ChangeOutcome(result, applied=action)

    outcome = await _apply(db, user_id, action, target.records, now)
    outcome.result.restored = restored
    return outcome
