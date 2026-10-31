"""Тексты ответа на создание, справку, ошибки и вопросы — `docs/assistant-texts.md`, разделы 5,
6, 10, 11. Списки — `list_replies.py`, поиск — `search_replies.py`, изменения —
`change_replies.py`.

Текст для чата собирает шаблон, а не берёт `ActionResult.error` сервиса как есть: тексты сервисов
показывают и кнопки «Моих дел» (`/api/items`), их здесь не меняем.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from schemas import ActionResult, CreateRecord, Help, ListRecords, Record, RecordType, SearchRecords

from .list_replies import reply_for_list
from .search_replies import reply_for_search
from .spoken import (
    at_time,
    capitalized,
    day_full,
    day_on,
    day_until,
    day_words,
    moment_full,
    moment_short,
    spoken_title,
    with_date,
)

# Раздел 11.1: каждая ошибка прямо говорит, что сохранено.
NOT_CONFIGURED = "Ассистент не настроен: задайте ключ и модель в настройках. Ничего не сохранено."
MODEL_DOWN = "Ассистент сейчас не отвечает. Ничего не сохранено, попробуйте ещё раз чуть позже."
NOT_PARSED = (
    "Не понял запрос, ничего не сохранено. Скажите иначе, например: "
    "«Напомни завтра в 10 позвонить Ивану»."
)
# Раздел 5.4: отказ посреди уточнения.
REFUSED_DRAFT = "Хорошо, ничего не записал."
REFUSED_CHOICE = "Хорошо, ничего не менял."
SAY_REST = "Остальное скажите отдельно."

# Раздел 6.2: вопросы о недостающем, которые пишет код.
ASK_TIME = "На какое время поставить встречу?"
ASK_DAY_AND_TIME = "На какой день и во сколько поставить встречу?"
ASK_DETAILS = "Не хватает деталей. Что и когда записать?"

HELP = (
    "Я помогаю вести задачи, встречи и напоминания. Например: «Напомни завтра в 10 позвонить "
    "Ивану», «Что у меня на неделе» или «Найди задачу про договор»."
)
OFFTOPIC = (
    "С этим не помогу: я веду задачи, встречи и напоминания. Например: «Что у меня сегодня» "
    "или «Поставь встречу с командой завтра в 15:00»."
)


def question_for_missing(missing: list[str], draft: object | None = None) -> str:
    """Вопрос о недостающем. Встреча без времени: день назван — «на какое время», не назван —
    «на какой день и во сколько». Остальные вопросы пишет модель (`AskUser.question`)."""
    if "start" in missing:
        has_day = isinstance(draft, CreateRecord) and draft.start is not None
        return ASK_TIME if has_day else ASK_DAY_AND_TIME
    return ASK_DETAILS


def draft_reminder(title: str | None, missing: list[str], draft: object | None) -> str:
    """Раздел 6.3: черновик ждёт ещё ход — «Запись «…» так и не создана — на какое время?»."""
    if not title:
        return "Действие ещё не завершено. " + question_for_missing(missing, draft)
    question = question_for_missing(missing, draft)
    if question == ASK_TIME:
        tail = "на какое время?"
    elif question == ASK_DAY_AND_TIME:
        tail = "на какой день и во сколько?"
    else:
        return f"Запись «{title}» так и не создана. {question}"
    return f"Запись «{title}» так и не создана — {tail}"


# --- создание ------------------------------------------------------------------------------


def _day(moment: datetime, tz: ZoneInfo):
    return moment.astimezone(tz).date()


def confirm_created(record: Record, tz: ZoneInfo, now: datetime) -> str:
    """Разделы 5.1–5.3: тип записи в тексте, день словами и число, время."""
    today = now.astimezone(tz).date()
    title = record.title
    timed = record.start is not None and not record.all_day
    if record.type == RecordType.MEETING:
        if record.start is None:
            return f"Добавил в календарь: {spoken_title(title)}."
        start = record.start.astimezone(tz)
        if record.end is not None:
            end = record.end.astimezone(tz)
            return (f"Добавил в календарь: {spoken_title(title)}, "
                    f"{day_full(start.date(), today)}, с {start:%H:%M} до {end:%H:%M}.")
        return f"Добавил в календарь: {spoken_title(title)}, {moment_full(start, today)}."
    if record.type == RecordType.REMINDER:
        if timed:
            when = moment_full(record.start.astimezone(tz), today)
            return f"Напомню {when}: {spoken_title(title)}."
        moment = record.start or record.deadline
        if moment is not None:
            return (f"Напомню {day_full(_day(moment, tz), today)}, в течение дня: "
                    f"{spoken_title(title)}.")
        return f"Добавил напоминание «{title}» без даты."
    if timed:
        start = record.start.astimezone(tz)
        on = with_date(day_on(start.date(), today), start.date(), today)
        return f"Добавил задачу «{title}» {at_time(on, start)}."
    if record.start is not None:
        day = _day(record.start, tz)
        return f"Добавил задачу «{title}» {with_date(day_on(day, today), day, today)}."
    if record.deadline is not None:
        day = _day(record.deadline, tz)
        return f"Добавил задачу «{title}» со сроком {with_date(day_until(day, today), day, today)}."
    return f"Добавил задачу «{title}» без даты."


def conflicts_note(conflicts: list[Record], tz: ZoneInfo, now: datetime) -> str:
    """Раздел 5.4: встреча сохранена, ответ предупреждает; вопроса «Перенести?» нет."""
    if not conflicts:
        return ""
    if len(conflicts) >= 3:
        return f" Пересекается с {len(conflicts)} записями."
    today = now.astimezone(tz).date()
    parts = [
        f"«{record.title}» ({moment_short(record.start.astimezone(tz), today)})"
        if record.start is not None else f"«{record.title}»"
        for record in conflicts
    ]
    return " Пересекается с " + " и ".join(parts) + "."


def _create_failed(result: ActionResult, action: CreateRecord | None, tz: ZoneInfo,
                   now: datetime) -> str:
    today = now.astimezone(tz).date()
    if result.records:
        # Точный дубль: сервис вернул найденную запись.
        dup = result.records[0]
        when = (moment_full(dup.start.astimezone(tz), today)
                if dup.start is not None and not dup.all_day
                else day_full(_day(dup.start or dup.deadline, tz), today)
                if (dup.start or dup.deadline) is not None else "")
        tail = f" — {when}" if when else ""
        return f"Такая запись уже есть: «{dup.title}»{tail}. Новую не создавал."
    if action is not None:
        moment = action.start or action.deadline
        if moment is not None:
            local = moment.astimezone(tz)
            timed = action.start is not None and action.time_given is not False
            if timed and local < now:
                return (f"{capitalized(moment_short(local, today))} уже прошло, запись не создана. "
                        "Назовите другое время.")
            if not timed and local.date() < today:
                return (f"{capitalized(day_words(local.date(), today))} уже прошло, "
                        "запись не создана. Назовите другую дату.")
    error = result.error or "Не получилось создать запись."
    return f"{error} Запись не создана."


def reply_for_result(
        result: ActionResult,
        timezone_name: str,
        action: CreateRecord | ListRecords | SearchRecords | Help | None = None,
        now: datetime | None = None,
) -> str:
    tz = ZoneInfo(timezone_name)
    now = now.astimezone(tz) if now is not None else datetime.now(tz)
    if result.action == "help":
        return OFFTOPIC if isinstance(action, Help) and action.kind == "offtopic" else HELP
    if result.action == "create_record":
        if not result.ok:
            return _create_failed(result, action if isinstance(action, CreateRecord) else None,
                                  tz, now)
        replies = [confirm_created(record, tz, now) for record in result.records]
        return " ".join(replies) + conflicts_note(result.conflicts, tz, now)
    if not result.ok:
        return result.error or "Не получилось выполнить запрос, ничего не изменено."
    if result.action == "list_records" and isinstance(action, ListRecords):
        return reply_for_list(result.records, action, timezone_name, now)
    if result.action == "search_records" and isinstance(action, SearchRecords):
        return reply_for_search(
            result.records, action.query, timezone_name, now,
            similar=getattr(result, "similar", False), filters=action.filters,
        )
    return "Готово."
