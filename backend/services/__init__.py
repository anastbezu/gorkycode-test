"""Сервисный слой: бизнес-логика между агентом / API и хранилищем.

Принимает и возвращает только Pydantic-модели контрактов (`schemas`).
"""

from .conversation import (
    ConversationAccessError,
    clear_pending,
    get_conversation_state,
    get_or_create_conversation_state,
    merge_pending,
    save_conversation_state,
)
from .records import (
    RecordChange,
    create_record,
    find_conflicts,
    find_duplicate,
    list_records_for_period,
    list_undated_records,
    set_status,
    update_record,
)

__all__ = [
    "ConversationAccessError",
    "RecordChange",
    "find_conflicts",
    "find_duplicate",
    "set_status",
    "update_record",
    "clear_pending",
    "create_record",
    "get_conversation_state",
    "get_or_create_conversation_state",
    "list_records_for_period",
    "list_undated_records",
    "merge_pending",
    "save_conversation_state",
]
