# Контракт: API чата

Граница: фронтенд (Настя) ↔ бэкенд (Денис). Pydantic v2, документация OpenAPI — `/docs`. `ActionResult` — `agent-tools.md`.

```python
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field

class LLMConfig(BaseModel):
    base_url: str | None = Field(default=None, description="OpenAI-совместимый base_url")
    api_key: str | None = Field(default=None, description="Ключ API пользователя")
    model: str | None = Field(default=None, description="Имя модели у провайдера")

class ChatRequest(BaseModel):
    conversation_id: UUID | None = None  # None — новый разговор
    text: str
    timezone: str = Field(description="IANA-пояс браузера, напр. Europe/Moscow")
    llm_config: LLMConfig | None = Field(default=None, description="Пользовательские настройки LLM (если заданы в браузере)")

class ChatResponse(BaseModel):
    conversation_id: UUID
    reply: str                          # текст ответа пользователю
    result: ActionResult | None = None  # что сделано — для показа в интерфейсе
    awaiting: Literal["answer", "choice"] | None = None  # ассистент ждёт ответа или выбора
```

## Правила
- Клиент шлёт только новую реплику, `conversation_id` и часовой пояс; историю и состояние разговора хранит сервер.
- Голосовой вход (аудио → текст → тот же `ChatRequest`) — после выбора STT.
- Пользовательские настройки LLM (`llm_config`): если переданы, сервер использует их для обращения к модели; если нет — используются настройки по умолчанию из `.env` сервера (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`). Сервер ключ не сохраняет.
- Пользователь — анонимный идентификатор браузера, не в теле запроса: заголовок `X-User-Id` (UUID). Без заголовка сервер выдаёт новый UUID в заголовке ответа `X-User-Id`; значение не UUID — 400.
- `GET /api/items` — `list[Record]` для боковой панели «Мои дела»:
  - `from`, `to` — обязательные, ISO 8601 со смещением, период `[from, to)`;
  - `type` — фильтр по типу, можно несколько;
  - `tz` — IANA-пояс, даты в ответе — в этом поясе;
  - `include_undated` (по умолчанию `false`) — добавить в конец активные записи без даты (`start` и `deadline` пустые) для блока «Без срока».
- `POST /api/chat`: чужой или несуществующий `conversation_id` → 404, неизвестный `timezone` → 422.
