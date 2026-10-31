"""Ответ на список за период — `docs/assistant-texts.md`, разделы 4 и 8.

Итог и не больше трёх записей по времени, как на экране; дальше «Остальные на экране».
Полный пронумерованный список интерфейс берёт из `result.records`; повторы в тексте списка
не сворачиваются.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from schemas import ListRecords, Record, RecordType

from .presentation import record_moment
from .spoken import (
    DEED_WORDS,
    TYPE_WORDS,
    capitalized,
    counted,
    date_text,
    day_on,
    day_words,
    moment_short,
    plural,
    spoken_title,
)

MAX_SPOKEN = 3
TASKS_AND_REMINDERS = {RecordType.TASK, RecordType.REMINDER}

__all__ = ["MAX_SPOKEN", "Period", "period_of", "plural", "reply_for_list"]


class Period:
    """Как назвать период по датам (раздел 4, «Названия периодов»).

    `lead` — начало фразы («На этой неделе», «Вчера», «До 25 октября»); `dash` — ставить ли
    тире перед итогом («На этой неделе — 2 встречи», но «На завтра одно дело»);
    `one_day` — записи называются без дня («08:00 — …»).
    """

    def __init__(self, lead: str, *, dash: bool, one_day: bool) -> None:
        self.lead, self.dash, self.one_day = lead, dash, one_day


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _clock(moment: datetime) -> str | None:
    return None if (moment.hour, moment.minute) == (0, 0) else f"{moment:%H:%M}"


def period_of(date_from: datetime | None, date_to: datetime | None, tz: ZoneInfo,
              today: date) -> Period | None:
    """Первая подходящая строка таблицы раздела 4 сверху вниз. `date_to` не включается:
    называется последний включённый день."""
    if date_from is None and date_to is None:
        return None
    start = date_from.astimezone(tz) if date_from is not None else None
    end = date_to.astimezone(tz) if date_to is not None else None
    since = f" с {_clock(start)}" if start is not None and _clock(start) else ""
    until = f" до {_clock(end)}" if end is not None and _clock(end) else ""

    if start is None:
        last = (end - timedelta(seconds=1)).date()
        return Period(f"До {date_text(last, today)}", dash=True, one_day=False)
    first = start.date()
    if end is None:
        return Period(f"Начиная с {date_text(first, today)}", dash=True, one_day=False)
    last = (end - timedelta(seconds=1)).date()

    if last <= first:
        if first < today:
            return Period(capitalized(day_words(first, today)) + since + until,
                          dash=True, one_day=True)
        return Period(capitalized(day_on(first, today)) + since + until, dash=False, one_day=True)
    week = _monday(today)
    if first.weekday() == 0 and (last - first).days == 6:
        if first == week:
            return Period("На этой неделе", dash=True, one_day=False)
        if first == week + timedelta(days=7):
            return Period("На следующей неделе", dash=True, one_day=False)
        if first == week - timedelta(days=7):
            return Period("На прошлой неделе", dash=True, one_day=False)
    if first.weekday() == 5 and (last - first).days == 1 and 0 <= (first - today).days <= 6:
        return Period("На выходных", dash=True, one_day=False)
    if first == today:
        return Period(f"До {date_text(last, today)}", dash=True, one_day=False)
    return Period(f"С {date_text(first, today)} по {date_text(last, today)}",
                  dash=True, one_day=False)


def _words(action: ListRecords) -> tuple[str, str, str]:
    """Слово итога по типу в запросе: один тип — его слово; все или «задачи и напоминания» —
    «дело» (раздел 8.1)."""
    kinds = set(action.types or [])
    if len(kinds) == 1:
        return TYPE_WORDS[next(iter(kinds))]
    return DEED_WORDS


def item_phrase(record: Record, tz: ZoneInfo, today: date, one_day: bool) -> str:
    """«08:00 — встреча с Марией», «в субботу в 10:45 — …», «отчёт (без срока)»."""
    title = spoken_title(record.title)
    moment = record.start or record.deadline
    if moment is None:
        return f"{title} (без срока)"
    local = moment.astimezone(tz)
    if record.start is not None and not record.all_day:
        head = f"{local:%H:%M}" if one_day else moment_short(local, today)
        return f"{head} — {title}"
    if one_day:
        return title
    return f"{day_words(local.date(), today)} — {title}"


def reply_for_list(records: list[Record], action: ListRecords,
                   timezone_name: str, now: datetime) -> str:
    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()
    period = period_of(action.date_from, action.date_to, tz, today)
    lead = period.lead if period else "Всего"
    words = _words(action)

    if not records:
        if words is DEED_WORDS:
            return f"{lead} ничего не запланировано."
        return f"{lead} {words[2]} нет."

    # По времени, как на экране; без даты — в конце.
    ordered = sorted(records, key=lambda r: ((r.start or r.deadline) is None, record_moment(r)))
    one_day = bool(period and period.one_day)
    phrases = [item_phrase(record, tz, today, one_day) for record in ordered[:MAX_SPOKEN]]
    items = "; ".join(phrases)
    total = counted(len(records), words)
    sep = " — " if period is None or period.dash else " "
    if len(records) <= MAX_SPOKEN:
        return f"{lead}{sep}{total}: {items}."
    return f"{lead} — {total}. Первые по времени: {items}. Остальные на экране."
