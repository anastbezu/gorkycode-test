"""Компактное состояние для LLM: структурированные данные без истории сообщений."""

import json
from zoneinfo import ZoneInfo

from schemas import ConversationState, Record


def build_draft_context(state: ConversationState) -> str:
    if state.pending is None:
        return ""
    data = {
        "pending": state.pending.model_dump(mode="json"),
        "missing": state.missing,
        "awaiting": state.awaiting,
    }
    return "[Черновик: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "]"


def build_focus_context(record: Record, timezone_name: str) -> str:
    data = {
        "title": record.title,
        "start": (
            record.start.astimezone(ZoneInfo(timezone_name)).isoformat()
            if record.start is not None else None
        ),
        "all_day": record.all_day,
    }
    return "[В фокусе: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "]"
