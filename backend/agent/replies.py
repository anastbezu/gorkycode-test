from zoneinfo import ZoneInfo

from .models import ActionResult, Record

MISSING_QUESTIONS = {
    "start": "На какое время поставить встречу?",
}


def question_for_missing(missing: list[str]) -> str:
    for field in missing:
        if field in MISSING_QUESTIONS:
            return MISSING_QUESTIONS[field]
    return "Уточните, пожалуйста, детали."


def when_text(record: Record, timezone_name: str) -> str:
    moment = record.start or record.deadline
    if moment is None:
        return ""
    local = moment.astimezone(ZoneInfo(timezone_name))
    prefix = "до" if record.start is None else "на"
    if record.all_day:
        return f"{prefix} {local:%d.%m}"
    return f"{prefix} {local:%d.%m} в {local:%H:%M}"


def reply_for_result(result: ActionResult, timezone_name: str) -> str:
    if not result.ok:
        return result.error or "Не получилось выполнить запрос."
    if result.action == "create_record":
        record = result.records[0]
        return f"Готово: «{record.title}» {when_text(record, timezone_name)}".strip() + "."
    # TODO(agent-04): короткие ответы на слух для списка и поиска
    if result.action == "list_records":
        return f"Нашёл записей: {len(result.records)}." if result.records else "На этот период ничего нет."
    if result.action == "search_records":
        return f"Нашёл записей: {len(result.records)}." if result.records else "Ничего не нашлось."
    return "Готово."