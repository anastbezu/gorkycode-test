"""Даты, время и слова для текста ответа — `docs/assistant-texts.md`, разделы 2 и 4.

Один текст ответа и для чата, и для голоса, поэтому дат вида `22.10` в нём нет: синтез речи
читает их как дробь. Ближайшие дни — словами, от 3 до 6 дней вперёд — днём недели, дальше —
датой; другой год — с годом.
"""

from datetime import date, datetime

from schemas import Record, RecordType

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]
# «в пятницу» / «на пятницу» / «до пятницы»
WEEKDAY_IN = ["в понедельник", "во вторник", "в среду", "в четверг",
              "в пятницу", "в субботу", "в воскресенье"]
WEEKDAY_ON = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
WEEKDAY_UNTIL = ["понедельника", "вторника", "среды", "четверга", "пятницы", "субботы",
                 "воскресенья"]
RELATIVE = {-1: "вчера", 0: "сегодня", 1: "завтра", 2: "послезавтра"}

# Слово типа и согласование с числом (1, 2–4, 5+, 11–14): раздел 7 и 8.1.
TYPE_WORDS = {
    RecordType.MEETING: ("встреча", "встречи", "встреч"),
    RecordType.TASK: ("задача", "задачи", "задач"),
    RecordType.REMINDER: ("напоминание", "напоминания", "напоминаний"),
}
RECORD_WORDS = ("запись", "записи", "записей")
DEED_WORDS = ("дело", "дела", "дел")
ONE = {"встреча": "одна встреча", "задача": "одна задача", "напоминание": "одно напоминание",
       "запись": "одна запись", "дело": "одно дело"}


def plural(n: int, one: str, few: str, many: str) -> str:
    if 11 <= n % 100 <= 14:
        return many
    if n % 10 == 1:
        return one
    if 2 <= n % 10 <= 4:
        return few
    return many


def counted(n: int, words: tuple[str, str, str]) -> str:
    """«одна встреча», «2 встречи», «5 дел» — числа цифрами (раздел 4), кроме «один»."""
    if n == 1:
        return ONE[words[0]]
    return f"{n} {plural(n, *words)}"


def type_words(records: list[Record]) -> tuple[str, str, str]:
    """Все одного типа — слово типа, разные — «запись» (разделы 7 и 9)."""
    kinds = {record.type for record in records}
    if len(kinds) == 1:
        return TYPE_WORDS[next(iter(kinds))]
    return RECORD_WORDS


def feminine(words: tuple[str, str, str]) -> bool:
    """«Последняя встреча», но «последнее напоминание»."""
    return words[0] != "напоминание"


def spoken_title(title: str) -> str:
    """Название после двоеточия и в строке списка — с маленькой буквы (раздел 2).
    «CRM планёрка» не трогаем: вторая буква заглавная — это аббревиатура."""
    if len(title) > 1 and title[1].isupper():
        return title
    return title[:1].lower() + title[1:]


def date_text(day: date, today: date) -> str:
    text = f"{day.day} {MONTHS[day.month - 1]}"
    if day.year != today.year:
        text += f" {day.year} года"
    return text


def _near(day: date, today: date) -> int | None:
    diff = (day - today).days
    return diff if 3 <= diff <= 6 else None


def day_words(day: date, today: date) -> str:
    """«вчера», «сегодня», «завтра», «послезавтра», «в субботу», «28 октября»."""
    diff = (day - today).days
    if diff in RELATIVE:
        return RELATIVE[diff]
    if _near(day, today) is not None:
        return WEEKDAY_IN[day.weekday()]
    return date_text(day, today)


def day_on(day: date, today: date) -> str:
    """Форма «на …»: «на завтра», «на субботу», «на 31 октября»."""
    diff = (day - today).days
    if diff in RELATIVE:
        return f"на {RELATIVE[diff]}"
    if _near(day, today) is not None:
        return f"на {WEEKDAY_ON[day.weekday()]}"
    return f"на {date_text(day, today)}"


def day_until(day: date, today: date) -> str:
    """Форма «до …»: «до завтра», «до воскресенья», «до 1 ноября»."""
    diff = (day - today).days
    if diff in RELATIVE:
        return f"до {RELATIVE[diff]}"
    if _near(day, today) is not None:
        return f"до {WEEKDAY_UNTIL[day.weekday()]}"
    return f"до {date_text(day, today)}"


def _is_date(words: str) -> bool:
    return any(ch.isdigit() for ch in words)


def with_date(words: str, day: date, today: date) -> str:
    """К слову дня — число месяца: «завтра, 22 октября», «на субботу, 24 октября».
    «Сегодня» и «вчера» числа не получают, дата — второй раз тоже."""
    if _is_date(words) or (day - today).days in (-1, 0):
        return words
    return f"{words}, {date_text(day, today)}"


def day_full(day: date, today: date) -> str:
    """«завтра, 22 октября», «в понедельник, 26 октября», «31 октября», «сегодня»."""
    return with_date(day_words(day, today), day, today)


def at_time(day_part: str, moment: datetime) -> str:
    """Запятая перед «в» — только после числа: «завтра в 15:00», «28 октября, в 13:15»,
    «завтра, 22 октября, в 15:00»."""
    sep = ", " if _is_date(day_part) else " "
    return f"{day_part}{sep}в {moment:%H:%M}"


def moment_full(moment: datetime, today: date) -> str:
    """{когда} в подтверждениях: день словами, число месяца, время (раздел 4)."""
    return at_time(day_full(moment.date(), today), moment)


def moment_short(moment: datetime, today: date) -> str:
    """{когда} в списках и поиске — без повторного числа: «завтра в 15:00»,
    «в субботу в 10:45», «29 октября, в 15:30»."""
    return at_time(day_words(moment.date(), today), moment)


def record_when(record: Record, tz, today: date, *, full: bool) -> str:
    """Когда у записи: время — если оно есть; «весь день» и срок — только день; без даты — ""."""
    moment = record.start or record.deadline
    if moment is None:
        return ""
    local = moment.astimezone(tz)
    if record.start is not None and not record.all_day:
        return moment_full(local, today) if full else moment_short(local, today)
    return day_full(local.date(), today) if full else day_words(local.date(), today)


def capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]
