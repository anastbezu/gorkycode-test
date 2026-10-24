# Контракт: API чата

Граница: фронтенд (Настя) ↔ бэкенд (Денис). Pydantic v2, документация OpenAPI — `/docs`. `ActionResult` — `agent-tools.md`.

```python
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    conversation_id: UUID | None = None  # None — новый разговор
    text: str
    timezone: str = Field(description="IANA-пояс браузера, напр. Europe/Moscow")

class ChatResponse(BaseModel):
    conversation_id: UUID
    reply: str                          # текст ответа пользователю
    result: ActionResult | None = None  # что сделано — для показа в интерфейсе
    awaiting: Literal["answer", "choice"] | None = None  # ассистент ждёт ответа или выбора
```

## Правила
- Клиент шлёт только новую реплику, `conversation_id` и часовой пояс; историю и состояние разговора хранит сервер.
- Пользователь — анонимный идентификатор браузера, не в теле запроса. Как он передаётся (cookie или заголовок) — решает владелец API.
- Голосовой вход (аудио → текст → тот же `ChatRequest`) — после выбора STT.
