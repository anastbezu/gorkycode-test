"""Компактное состояние для LLM: структурированные данные без истории сообщений."""

import json
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from schemas import ConversationState, Record

from .presentation import MAX_SHOWN


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(
        "\u2028", "\\u2028"
    ).replace("\u2029", "\\u2029")


def _local_dates(value: object, timezone_name: str) -> object:
    if isinstance(value, datetime):
        return value.astimezone(ZoneInfo(timezone_name)).isoformat(timespec="seconds")
    if isinstance(value, dict):
        return {key: _local_dates(item, timezone_name) for key, item in value.items()}
    if isinstance(value, list):
        return [_local_dates(item, timezone_name) for item in value]
    return value


def build_draft_context(state: ConversationState, timezone_name: str = "UTC") -> str:
    if state.pending is None:
        return ""
    data = {
        "pending": _local_dates(state.pending.model_dump(exclude_none=True), timezone_name),
        "missing": state.missing,
        "awaiting": state.awaiting,
    }
    return "[Черновик: " + _json(data) + "]"


def build_focus_context(record: Record, timezone_name: str) -> str:
    data = {
        "type": record.type,
        "title": record.title,
        "start": (
            record.start.astimezone(ZoneInfo(timezone_name)).isoformat()
            if record.start is not None else None
        ),
        "all_day": record.all_day,
    }
    if record.end is not None:
        data["end"] = record.end.astimezone(ZoneInfo(timezone_name)).isoformat()
    if record.deadline is not None:
        data["deadline"] = record.deadline.astimezone(ZoneInfo(timezone_name)).isoformat()
    if record.status != "active":
        data["status"] = record.status
    return "[В фокусе: " + _json(data) + "]"


def record_summary(record: Record, timezone_name: str) -> str:
    tz = ZoneInfo(timezone_name)
    parts = [record.type, _json(record.title)]
    if record.start is not None:
        local = record.start.astimezone(tz)
        parts.append(local.strftime("%d.%m.%Y весь день" if record.all_day else "%d.%m.%Y %H:%M"))
    if record.end is not None:
        parts.append("до " + record.end.astimezone(tz).strftime("%d.%m.%Y %H:%M"))
    if record.deadline is not None:
        parts.append("срок до " + record.deadline.astimezone(tz).strftime("%d.%m.%Y %H:%M"))
    if record.start is None and record.deadline is None:
        parts.append("без даты")
    if record.status != "active":
        parts.append("выполнено" if record.status == "done" else "отменено")
    return " ".join(parts)


def build_state_context(
    state: ConversationState, records: Mapping[UUID, Record], timezone_name: str,
) -> str:
    """Не больше четырёх строк; только доступные записи, без UUID и before.

    Пропуски номеров сохраняются: index всегда указывает в исходный state.shown.
    Данные не загружаются здесь, чтобы функция оставалась чистой.
    """
    available = {
        key: record for key, record in records.items()
        if record.user_id == state.user_id and record.id == key
    }
    lines = []
    shown = [
        f"{index}) {record_summary(available[rid], timezone_name)}"
        for index, rid in enumerate(state.shown[:MAX_SHOWN], 1) if rid in available
    ]
    if shown:
        lines.append("Показано: " + "; ".join(shown))
    if state.focus_record_id in available:
        lines.append(build_focus_context(available[state.focus_record_id], timezone_name))
    if state.last_action is not None:
        last = state.last_action
        summaries = [
            record_summary(available[rid], timezone_name)
            for rid in last.record_ids[:3] if rid in available
        ]
        text = "; ".join(summaries) or "записи недоступны"
        if len(last.record_ids) > 3:
            text += f"; всего {len(last.record_ids)}"
        lines.append(f"Последнее действие: {last.action}; {text}")
    if draft := build_draft_context(state, timezone_name):
        lines.append(draft)
    elif state.awaiting:
        lines.append("Уточнение: " + _json({"missing": state.missing, "awaiting": state.awaiting}))
    return "\n".join(lines)
