"""Ответ на поиск — `docs/assistant-texts.md`, разделы 4 и 9.

Называется одна запись: «Ближайшая» (есть будущие) или «Последняя» (все в прошлом). Записи
с одинаковым названием сворачиваются только в тексте: ««…» — 6 раз»; на экране и в номерах
они отдельные строки. Ничего не нашлось — без вопроса: «Поискать шире?» не будет понято.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from schemas import Record, SearchFilters

from .list_replies import MAX_SPOKEN, period_of
from .spoken import (
    counted,
    day_words,
    feminine,
    moment_short,
    plural,
    type_words,
)


def when_phrase(record: Record, tz: ZoneInfo, today) -> str:
    """«22 августа, в 20:30», «завтра в 11:00»; без времени — только день."""
    moment = record.start or record.deadline
    if moment is None:
        return "без даты"
    local = moment.astimezone(tz)
    if record.start is not None and not record.all_day:
        return moment_short(local, today)
    return day_words(local.date(), today)


def _same_title(records: list[Record]) -> bool:
    titles = {" ".join(record.title.lower().split()) for record in records}
    return len(titles) == 1


def _dated(records: list[Record]) -> list[Record]:
    return [record for record in records if (record.start or record.deadline) is not None]


def _named(records: list[Record], now: datetime) -> tuple[Record, bool] | None:
    """Ближайшая будущая, иначе последняя прошедшая — по датам записей (раздел 9.1)."""
    dated = _dated(records)
    if not dated:
        return None
    future = [r for r in dated if (r.start or r.deadline) >= now]
    if future:
        return min(future, key=lambda r: r.start or r.deadline), True
    return max(dated, key=lambda r: r.start or r.deadline), False


def _times(records: list[Record]) -> str:
    """««Демо проекта» — 8 раз»."""
    n = len(records)
    return f"«{records[0].title}» — {n} {plural(n, 'раз', 'раза', 'раз')}"


def _nearest_word(future: bool, words: tuple[str, str, str]) -> str:
    if feminine(words):
        return "Ближайшая" if future else "Последняя"
    return "Ближайшее" if future else "Последнее"


def reply_for_search(
    records: list[Record], query: str, timezone_name: str, now: datetime, *,
    similar: bool = False, filters: SearchFilters | None = None,
) -> str:
    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()

    if not records:
        period = (period_of(filters.date_from, filters.date_to, tz, today)
                  if filters is not None else None)
        if period is not None:
            return (f"{period.lead} по запросу «{query}» ничего не нашлось. "
                    "Попробуйте другой период или другие слова.")
        return f"По запросу «{query}» ничего не нашлось. Попробуйте другие слова."

    words = type_words(records)

    if similar:
        if len(records) > 1 and _same_title(records):
            named = _named(records, now)
            head = _times(records)
            if named is not None:
                record, future = named
                nearest = _nearest_word(future, words).lower()
                head += f", {nearest} — {when_phrase(record, tz, today)}"
            return f"Точно не нашёл «{query}». Похожие: {head}."
        phrases = [f"«{r.title}» — {when_phrase(r, tz, today)}" for r in records[:MAX_SPOKEN]]
        tail = " Остальные на экране." if len(records) > MAX_SPOKEN else ""
        return f"Точно не нашёл «{query}». Похожие: {'; '.join(phrases)}.{tail}"

    if len(records) == 1:
        record = records[0]
        return f"«{record.title}» — {when_phrase(record, tz, today)}."

    named = _named(records, now)
    if _same_title(records):
        head = _times(records) + "."
        if named is None:
            return head
        record, future = named
        return f"{head} {_nearest_word(future, words)} — {when_phrase(record, tz, today)}."

    head = f"Нашёл {counted(len(records), words)}."
    if named is None:
        return head
    record, future = named
    return (f"{head} {_nearest_word(future, words)} — {when_phrase(record, tz, today)}: "
            f"«{record.title}».")
