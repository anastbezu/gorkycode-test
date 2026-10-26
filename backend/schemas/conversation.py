"""Состояние разговора (хранится на сервере).

Контракт: docs/contracts/data-model.md. Вынесено в отдельный файл,
потому что ссылается и на Record, и на LLMAction.
"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .actions import LLMAction


class LastAction(BaseModel):
    """Последнее изменение — для поправки, отката и замены цели."""

    action: str  # create_record, update_record, set_status
    record_ids: list[UUID]  # какие записи затронуты
    before: list[dict[str, Any]] = []  # прежние значения изменённых полей; у создания — пусто


class ConversationState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: UUID
    user_id: UUID
    focus_record_id: UUID | None = None  # «её», «эту встречу»
    shown: list[UUID] = []  # записи в порядке, в каком их назвали пользователю
    last_action: LastAction | None = None  # последнее изменение — для поправки и отката
    pending: LLMAction | None = None  # действие ждёт недостающих полей
    pending_skipped: bool = False  # прошлая реплика была не про черновик
    candidates: list[UUID] = []  # ждём выбора из нескольких записей
    missing: list[str] = []  # каких полей не хватает для pending
    awaiting: Literal["answer", "choice"] | None = None  # ассистент ждёт ответа или выбора
