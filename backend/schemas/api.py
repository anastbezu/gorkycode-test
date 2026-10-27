"""Формат запросов и ответов API: чат и распознавание речи.

Контракт: docs/contracts/api.md. Менять только через техлида.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .actions import ActionResult


class LLMConfig(BaseModel):
    base_url: str | None = Field(default=None, description="OpenAI-совместимый base_url")
    api_key: str | None = Field(default=None, description="Ключ API пользователя")
    model: str | None = Field(default=None, description="Имя модели у провайдера")


class ChatRequest(BaseModel):
    conversation_id: UUID | None = None  # None — новый разговор
    text: str
    timezone: str = Field(description="IANA-пояс браузера, напр. Europe/Moscow")
    llm_config: LLMConfig | None = Field(
        default=None, description="Пользовательские настройки LLM (если заданы в браузере)"
    )


class ChatResponse(BaseModel):
    conversation_id: UUID
    reply: str                          # текст ответа пользователю
    result: ActionResult | None = None  # что сделано — для показа в интерфейсе
    awaiting: Literal["answer", "choice"] | None = None  # ассистент ждёт ответа или выбора


class STTResponse(BaseModel):
    text: str  # распознанная реплика как есть: не пустая, без правок и сокращений
