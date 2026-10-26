from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from schemas import ListRecords, Record

MAX_SPOKEN = 3

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]
IN_WEEKDAY = ["в понедельник", "во вторник", "в среду", "в четверг",
              "в пятницу", "в субботу", "в воскресенье"]


def plural(n: int, one: str, few: str, many: str) -> str:
    if 11 <= n % 100 <= 14:
        return many
    if n % 10 == 1:
        return one
    if 2 <= n % 10 <= 4:
        return few
    return many


def spoken_title(title: str) -> str:
    # «Подготовить акт» -> «подготовить акт», но «CRM планёрка» не трогаем
    if len(title) > 1 and title[1].isupper():
        return title
    return title[:1].lower() + title[1:]


def date_text(day: date, today: date) -> str:
    text = f"{day.day} {MONTHS[day.month - 1]}"
    if day.year != today.year:
        text += f" {day.year} года"
    return text


def day_words(day: date, today: date, weekday: bool = True) -> str:
    diff = (day - today).days
    if diff == -1:
        return "вчера"
    if diff == 0:
        return "сегодня"
    if diff == 1:
        return "завтра"
    if diff == 2:
        return "послезавтра"
    if weekday and 3 <= diff <= 6:
        return IN_WEEKDAY[day.weekday()]
    return date_text(day, today)


def period_phrase(action: ListRecords, tz: ZoneInfo, today: date) -> tuple[str, bool]:
    """Возвращает (фраза периода, период длиннее одного дня)."""
    first = action.date_from.astimezone(tz).date()
    if action.date_to is None:
        return "Начиная с " + date_text(first, today), True
    last = (action.date_to.astimezone(tz) - timedelta(seconds=1)).date()
    if last <= first:
        return "На " + day_words(first, today, weekday=False), False
    return f"С {date_text(first, today)} по {date_text(last, today)}", True


def item_phrase(record: Record, tz: ZoneInfo, today: date, with_day: bool) -> str:
    title = spoken_title(record.title)
    moment = record.start or record.deadline
    if moment is None:
        return f"{title} (без срока)"
    local = moment.astimezone(tz)
    has_time = record.start is not None and not record.all_day
    day = day_words(local.date(), today)
    if has_time:
        head = f"{day} в {local:%H:%M}" if with_day else f"{local:%H:%M}"
        return f"{head} — {title}"
    if with_day:
        return f"{day} — {title}"
    return title


def reply_for_list(records: list[Record], action: ListRecords,
                   timezone_name: str, now: datetime) -> str:
    """Короткий ответ на слух. Полный список интерфейс берёт из result.records."""
    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()
    period, multi_day = period_phrase(action, tz, today)
    lead = f"{period} —" if multi_day else period

    if not records:
        return f"{lead} ничего не запланировано."

    n = len(records)
    items = "; ".join(item_phrase(r, tz, today, multi_day) for r in records[:MAX_SPOKEN])

    if n == 1:
        return f"{lead} одно дело: {items}."
    head = f"{lead} {n} {plural(n, 'дело', 'дела', 'дел')}"
    if n <= MAX_SPOKEN:
        return f"{head}: {items}."
    return f"{head}. Ближайшие: {items}. Остальные на экране."
