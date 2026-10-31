"""Ответы на изменение, смену статуса, откат и выбор цели — `docs/assistant-texts.md`,
раздел 7 (agent-07, agent-09, agent-11).

Номера записей текст не повторяет: они на экране (`result.candidates`). «Выполнено» —
нейтрально, «как выполненное»: шаблон не согласует слово с родом названия.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from schemas import Record, RecordStatus, SetStatus, UndoLast, UpdateRecord

from .changes import ChangeOutcome
from .list_replies import MAX_SPOKEN, period_of
from .replies import conflicts_note
from .spoken import (
    counted,
    day_until,
    moment_short,
    record_when,
    spoken_title,
    type_words,
    with_date,
)
from .targets import NO_TARGET

UNDO_HINT = "Чтобы вернуть, скажите «верни»."
CONFIRM_QUESTIONS = {
    RecordStatus.CANCELLED: "Отменить все?",
    RecordStatus.DONE: "Отметить все выполненными?",
    RecordStatus.ACTIVE: "Вернуть все?",
}
VERBS = {
    RecordStatus.CANCELLED: "отменить",
    RecordStatus.DONE: "отметить",
    RecordStatus.ACTIVE: "вернуть",
}


def _when(record: Record, tz: ZoneInfo, today) -> str:
    return record_when(record, tz, today, full=True)


def _titled(record: Record, tz: ZoneInfo, today) -> str:
    """«Встреча с дизайнером» — завтра, 22 октября, в 11:00 (без даты — только название)."""
    when = _when(record, tz, today)
    return f"«{record.title}» — {when}" if when else f"«{record.title}»"


def _titles(records: list[Record]) -> str:
    """До трёх названий; больше трёх — «Остальные на экране.» добавляет вызывающий."""
    return "; ".join(f"«{record.title}»" for record in records[:MAX_SPOKEN])


def _many(verb: str, records: list[Record]) -> str:
    """«Отменил 5 записей: «…»; «…»; «…». Остальные на экране.»"""
    tail = " Остальные на экране." if len(records) > MAX_SPOKEN else ""
    return f"{verb} {counted(len(records), type_words(records))}: {_titles(records)}.{tail}"


def _moved(record: Record, tz: ZoneInfo, today) -> str:
    if record.start is not None:
        return f"теперь {_when(record, tz, today)}"
    if record.deadline is not None:
        day = record.deadline.astimezone(tz).date()
        return f"теперь срок {with_date(day_until(day, today), day, today)}"
    return "теперь без даты"


def _updated(outcome: ChangeOutcome, action: UpdateRecord, tz: ZoneInfo, now: datetime) -> str:
    today = now.date()
    record = outcome.result.records[0]
    renamed_only = action.title is not None and all(
        getattr(action, name) is None
        for name in ("start", "end", "deadline", "time_given", "shift_minutes")
    )
    if renamed_only:
        reply = f"Переименовал: теперь «{record.title}»."
    else:
        reply = f"Перенёс «{record.title}»: {_moved(record, tz, today)}."
    return reply + conflicts_note(outcome.result.conflicts, tz, now)


def _status_done(records: list[Record], status: RecordStatus, tz: ZoneInfo, today) -> str:
    if status == RecordStatus.DONE:
        if len(records) == 1:
            return f"Отметил как выполненное: «{records[0].title}»."
        return _many("Отметил как выполненные", records)
    if status == RecordStatus.CANCELLED:
        if len(records) == 1:
            return f"Отменил {_titled(records[0], tz, today)}. {UNDO_HINT}"
        return f"{_many('Отменил', records)} {UNDO_HINT}"
    if len(records) == 1:
        return f"Вернул {_titled(records[0], tz, today)}."
    return _many("Вернул", records)


def _restored(records: list[Record], tz: ZoneInfo, today) -> str:
    if len(records) == 1:
        return f"Вернул {_titled(records[0], tz, today)}."
    return _many("Вернул", records)


def _confirm_items(records: list[Record], action: SetStatus, tz: ZoneInfo, today) -> str:
    """Раздел 7: период команды — один день («всё на завтра») — день не называется:
    «09:15 — подготовить вопросы»; несколько дней — «завтра в 12:00 — созвон …»."""
    filters = action.target.filters
    period = (period_of(filters.date_from, filters.date_to, tz, today)
              if filters is not None else None)
    if period is not None:
        one_day = period.one_day
    else:
        days = {(r.start or r.deadline).astimezone(tz).date()
                for r in records if (r.start or r.deadline) is not None}
        one_day = len(days) <= 1
    phrases = []
    for record in records[:MAX_SPOKEN]:
        title = spoken_title(record.title)
        if record.start is not None and not record.all_day:
            local = record.start.astimezone(tz)
            head = f"{local:%H:%M}" if one_day else moment_short(local, today)
            phrases.append(f"{head} — {title}")
        else:
            phrases.append(title)
    return "; ".join(phrases)


def _choice_question(outcome: ChangeOutcome, action: UpdateRecord | SetStatus, tz: ZoneInfo,
                     today) -> str:
    candidates = outcome.result.candidates
    if outcome.similar:
        if len(candidates) == 1:
            record = candidates[0]
            when = record_when(record, tz, today, full=True)
            named = f"«{record.title}» — {when}" if when else f"«{record.title}»"
            return f"Точно такой нет. Может, {named}?"
        return "Точно такой нет. Может, одну из этих?"
    words = type_words(candidates)
    if outcome.confirm and isinstance(action, SetStatus):
        tail = " Остальные на экране." if len(candidates) > MAX_SPOKEN else ""
        items = _confirm_items(candidates, action, tz, today)
        question = CONFIRM_QUESTIONS[action.status]
        return f"Нашёл {counted(len(candidates), words)}: {items}.{tail} {question}"
    return f"Нашёл {counted(len(candidates), words)}. Какую именно?"


def _verb(action: UpdateRecord | SetStatus) -> str:
    if isinstance(action, SetStatus):
        return VERBS[action.status]
    return "перенести"


def _failed(error: str | None, action, shown_count: int) -> str:
    if error == NO_TARGET:
        name = "номер из списка" if shown_count > 1 else "её"
        return f"Не понял, какую запись {_verb(action)}. Назовите {name}."
    return error or "Не получилось изменить запись, ничего не изменено."


def reply_for_change(
    outcome: ChangeOutcome, action: UpdateRecord | SetStatus | UndoLast, timezone_name: str,
    now: datetime | None = None, *, shown_count: int = 0,
) -> str:
    tz = ZoneInfo(timezone_name)
    now = now.astimezone(tz) if now is not None else datetime.now(tz)
    today = now.date()
    result = outcome.result
    if isinstance(action, UndoLast):
        if not result.ok:
            return result.error or "Не получилось вернуть, ничего не изменено."
        if not result.restored:
            return "Вернул как было."
        return _restored(result.restored, tz, today)

    prefix = _restored(result.restored, tz, today) + " " if result.restored else ""
    if result.candidates:
        return prefix + _choice_question(outcome, action, tz, today)
    if not result.ok:
        return prefix + _failed(result.error, action, shown_count)
    if isinstance(action, UpdateRecord):
        return prefix + _updated(outcome, action, tz, now)
    return prefix + _status_done(result.records, action.status, tz, today)

