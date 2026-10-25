"""Состояние разговора (хранится на сервере).

Контракт: docs/contracts/data-model.md. Вынесено в отдельный файл,
потому что ссылается и на Record, и на LLMAction.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .actions import LLMAction


class ConversationState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: UUID
    user_id: UUID
    focus_record_id: UUID | None = None   # «её», «эту встречу»
    pending: LLMAction | None = None      # действие ждёт недостающих полей
    candidates: list[UUID] = []           # ждём выбора из нескольких записей
    missing: list[str] = []               # каких полей не хватает для pending
    awaiting: Literal["answer", "choice"] | None = None  # ассистент ждёт ответа или выбора
