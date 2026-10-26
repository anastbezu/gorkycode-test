from datetime import date, datetime
from zoneinfo import ZoneInfo

from schemas import Record

from .list_replies import day_words, plural


def record_moment(record: Record) -> datetime:
    return record.start or record.deadline or record.created_at


def when_phrase(record: Record, tz: ZoneInfo, today: date) -> str:
    local = record_moment(record).astimezone(tz)
    day = day_words(local.date(), today)
    if record.start is not None and not record.all_day:
        return f"{day}, в {local:%H:%M}"
    return day


def reply_for_search(records: list[Record], query: str, timezone_name: str, now: datetime) -> str:
    """Короткий ответ на поиск. Порядок записей не важен: «последнюю» ищем по дате сами."""
    if not records:
        return f"По запросу «{query}» ничего не нашлось. Попробуйте другие слова."

    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()
    latest = max(records, key=record_moment)
    when = when_phrase(latest, tz, today)

    if len(records) == 1:
        return f"«{latest.title}» — {when}."
    n = len(records)
    noun = plural(n, "запись", "записи", "записей")
    return f"Нашёл {n} {noun}. Последняя — {when}: «{latest.title}»."