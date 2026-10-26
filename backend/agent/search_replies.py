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


def pick_highlight(records: list[Record], now: datetime) -> tuple[Record, str]:
    """Какую запись назвать: ближайшую будущую, а если будущих нет — последнюю прошедшую."""
    upcoming = [r for r in records if record_moment(r) >= now]
    if upcoming:
        return min(upcoming, key=record_moment), "Ближайшая"
    return max(records, key=record_moment), "Последняя"


def reply_for_search(records: list[Record], query: str, timezone_name: str, now: datetime) -> str:
    """Короткий ответ на поиск. От порядка выдачи не зависит: запись выбираем по дате."""
    if not records:
        return f"По запросу «{query}» ничего не нашлось. Попробуйте другие слова."

    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()

    if len(records) == 1:
        record = records[0]
        return f"«{record.title}» — {when_phrase(record, tz, today)}."

    record, label = pick_highlight(records, now)
    n = len(records)
    noun = plural(n, "запись", "записи", "записей")
    return f"Нашёл {n} {noun}. {label} — {when_phrase(record, tz, today)}: «{record.title}»."
