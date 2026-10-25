"""Компактные инструкции с календарным контекстом запроса."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def format_iso_example(now: datetime) -> str:
    """Пример полного ISO datetime в уже выбранном поясе пользователя."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now должен содержать часовой пояс пользователя.")
    return now.replace(hour=15, minute=0, second=0, microsecond=0).isoformat(
        timespec="seconds"
    )


def build_compact_system_prompt(now: datetime, timezone_name: str) -> str:
    """Собрать промпт из одного снимка времени; системный пояс не используется."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now должен содержать информацию о часовом поясе.")

    local_now = now.astimezone(ZoneInfo(timezone_name))
    monday = local_now.date() - timedelta(days=local_now.weekday())
    weeks = []
    for week in range(2):
        days = [
            f"{WEEKDAYS_RU[day]} {(monday + timedelta(days=week * 7 + day)).isoformat()}"
            for day in range(7)
        ]
        weeks.append("; ".join(days))

    return "\n".join(
        [
            "Ты голосовой ассистент для задач, встреч и напоминаний.",
            "Помогай пользователю, вызывая ровно один подходящий инструмент на запрос.",
            "",
            "Контекст:",
            (
                f"- Текущее время: {local_now.isoformat(timespec='seconds')} "
                f"({WEEKDAYS_RU[local_now.weekday()]})"
            ),
            f"- Часовой пояс: {timezone_name}",
            f"- Текущая неделя: {weeks[0]}",
            f"- Следующая неделя: {weeks[1]}",
            "",
            "Правила:",
            (
                "1. Вызывай инструмент строго по схеме его параметров. "
                "Не придумывай данные и действия."
            ),
            (
                "2. Все даты и время возвращай в полном ISO 8601 со смещением "
                f"пояса пользователя, например: {format_iso_example(local_now)}."
            ),
            (
                "3. Относительные дни отсчитывай от контекста. "
                "«В пятницу», если сегодня пятница, означает следующую неделю."
            ),
            (
                "4. Если критически не хватает обязательных данных, "
                "вызывай ask_user. Не угадывай скрытые параметры."
            ),
        ]
    )
