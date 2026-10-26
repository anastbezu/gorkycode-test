from datetime import datetime
from zoneinfo import ZoneInfo

from schemas import ActionResult, ListRecords, Record

from .list_replies import reply_for_list

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


def reply_for_result(
        result: ActionResult,
        timezone_name: str,
        action: ListRecords | None = None,
        now: datetime | None = None,
) -> str:
    if not result.ok:
        return result.error or "Не получилось выполнить запрос."
    if result.action == "create_record":
        record = result.records[0]
        return f"Готово: «{record.title}» {when_text(record, timezone_name)}".strip() + "."
    if result.action == "list_records":
        if isinstance(action, ListRecords) and now is not None:
            return reply_for_list(result.records, action, timezone_name, now)
        if not result.records:
            return "На этот период ничего нет."
        return f"Нашёл записей: {len(result.records)}."
    # TODO(agent-04): короткий ответ на слух для поиска
    if result.action == "search_records":
        return f"Нашёл записей: {len(result.records)}." if result.records else "Ничего не нашлось."
    return "Готово."
