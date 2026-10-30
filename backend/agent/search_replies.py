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


def reply_for_search(
    records: list[Record], query: str, timezone_name: str, now: datetime, *,
    similar: bool = False,
) -> str:
    """Порядок групп совпадает с shown; представитель повторов — первый в порядке поиска
    (ближайший, search.md): будущий — «ближайший …», прошедший — «последний …».

    similar — точных нет, это похожие по смыслу (search.md): «Точно не нашёл …. Похожие: …».
    """
    if not records:
        return f"По запросу «{query}» ничего не нашлось. Попробуйте другие слова."

    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()

    if similar:
        phrases = [
            f"«{record.title}» — {when_phrase(record, tz, today)}"
            for record in records[:MAX_SPOKEN]
        ]
        tail = " Остальные на экране." if len(records) > MAX_SPOKEN else ""
        return f"Точно не нашёл «{query}». Похожие: {'; '.join(phrases)}.{tail}"

    if len(records) == 1:
        record = records[0]
        return f"«{record.title}» — {when_phrase(record, tz, today)}."

    n = len(records)
    noun = plural(n, "запись", "записи", "записей")
    groups = group_records(records, first_in_order=True)
    phrases = [
        group_phrase(group, tz, now) if group.count > 1
        else f"«{group.record.title}» — {when_phrase(group.record, tz, today)}"
        for group in groups[:MAX_SPOKEN]
    ]
    # Без номеров: группы повторов не совпадают с номерами на экране (api.md)
    items = "; ".join(phrases)
    tail = " Остальные на экране." if len(groups) > MAX_SPOKEN else ""
    return f"Нашёл {n} {noun}. {items}.{tail}"
