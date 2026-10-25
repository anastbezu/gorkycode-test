# Контракт: модель данных

Граница: хранилище (Денис) ↔ сервисы, агент, поиск, API. Pydantic v2.

## Запись
```python
from enum import StrEnum
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, model_validator

class RecordType(StrEnum):
    TASK = "task"
    MEETING = "meeting"
    REMINDER = "reminder"

class RecordStatus(StrEnum):
    ACTIVE = "active"
    DONE = "done"
    CANCELLED = "cancelled"

class Record(BaseModel):
    id: UUID
    user_id: UUID
    type: RecordType
    title: str
    start: AwareDatetime | None = None      # встреча и напоминание — когда; у задачи может не быть
    end: AwareDatetime | None = None        # только у встречи
    all_day: bool = False                   # дата названа, время — нет
    deadline: AwareDatetime | None = None   # срок («до конца недели»), не начало
    status: RecordStatus = RecordStatus.ACTIVE
    created_at: AwareDatetime

    @model_validator(mode="after")
    def check_times(self):
        if self.type is RecordType.MEETING and self.start is None:
            raise ValueError("meeting requires start")
        if self.end and self.start and self.end <= self.start:
            raise ValueError("end must be after start")
        return self
```

## Правила
- Время всегда с часовым поясом: значение без пояса не проходит валидацию.
- Дата без времени — `all_day = True`, а не полночь.
- `start` и `deadline` — разные поля.
- У каждой записи есть пользователь: без авторизации, пользователь — анонимный идентификатор браузера.
- Повторы в MVP не входят.

## Состояние разговора
Хранится на сервере, в той же базе.
```python
class ConversationState(BaseModel):
    conversation_id: UUID
    user_id: UUID
    focus_record_id: UUID | None = None   # «её», «эту встречу»
    pending: "LLMAction | None" = None    # действие ждёт недостающих полей (agent-tools.md)
    candidates: list[UUID] = []           # ждём выбора из нескольких записей
    missing: list[str] = []               # каких полей не хватает для pending
    awaiting: Literal["answer", "choice"] | None = None  # ассистент ждёт ответа или выбора
```
