"""Формат запроса и ответа чата.

Контракт: docs/contracts/api.md. Менять только через техлида.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .actions import ActionResult


class ChatRequest(BaseModel):
    conversation_id: UUID | None = None  # None — новый разговор
    text: str
    timezone: str = Field(description="IANA-пояс браузера, напр. Europe/Moscow")


class ChatResponse(BaseModel):
    conversation_id: UUID
    reply: str                          # текст ответа пользователю
    result: ActionResult | None = None  # что сделано — для показа в интерфейсе
    awaiting: Literal["answer", "choice"] | None = None  # ассистент ждёт ответа или выбора
