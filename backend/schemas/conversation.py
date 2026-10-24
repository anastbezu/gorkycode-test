"""Состояние разговора (хранится на сервере).

Контракт: docs/contracts/data-model.md. Вынесено в отдельный файл,
потому что ссылается и на Record, и на LLMAction.
"""

from uuid import UUID

from pydantic import BaseModel

from .actions import LLMAction


class ConversationState(BaseModel):
    conversation_id: UUID
    user_id: UUID
    focus_record_id: UUID | None = None   # «её», «эту встречу»
    pending: LLMAction | None = None      # действие ждёт недостающих полей
    candidates: list[UUID] = []           # ждём выбора из нескольких записей
