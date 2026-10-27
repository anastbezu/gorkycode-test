from datetime import date, datetime
from zoneinfo import ZoneInfo

from schemas import Record

from .list_replies import MAX_SPOKEN, day_words, group_phrase, plural
from .presentation import group_records, record_moment


def when_phrase(record: Record, tz: ZoneInfo, today: date) -> str:
    local = record_moment(record).astimezone(tz)
    day = day_words(local.date(), today)
    if record.start is not None and not record.all_day:
        return f"{day}, в {local:%H:%M}"
    return day


def reply_for_search(records: list[Record], query: str, timezone_name: str, now: datetime) -> str:
    """Порядок групп совпадает с shown; представитель повторов — последний по дате."""
    if not records:
        return f"По запросу «{query}» ничего не нашлось. Попробуйте другие слова."

    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()

    if len(records) == 1:
        record = records[0]
        return f"«{record.title}» — {when_phrase(record, tz, today)}."

    n = len(records)
    noun = plural(n, "запись", "записи", "записей")
    groups = group_records(records)
    phrases = [
        group_phrase(group, tz) if group.count > 1
        else f"«{group.record.title}» — {when_phrase(group.record, tz, today)}"
        for group in groups[:MAX_SPOKEN]
    ]
    items = "; ".join(
        f"{index}) {phrase}" if len(groups) > 1 else phrase
        for index, phrase in enumerate(phrases, 1)
    )
    tail = " Остальные на экране." if len(groups) > MAX_SPOKEN else ""
    return f"Нашёл {n} {noun}. {items}.{tail}"
