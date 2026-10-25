"""Сервисный слой: бизнес-логика между агентом / API и хранилищем.

Принимает и возвращает только Pydantic-модели контрактов (`schemas`).
"""

from .conversation import (
    ConversationAccessError,
    clear_pending,
    get_or_create_conversation_state,
    merge_pending,
    save_conversation_state,
)
from .records import create_record, list_records_for_period

__all__ = [
    "ConversationAccessError",
    "clear_pending",
    "create_record",
    "get_or_create_conversation_state",
    "list_records_for_period",
    "merge_pending",
    "save_conversation_state",
]
