# Контракт: действия агента

Граница: LLM ↔ агент (Илья, Давид) ↔ сервисы (Денис). Pydantic v2, типы записи — `data-model.md`.

Один вызов LLM на реплику: LLM возвращает одно действие с аргументами, код его исполняет. Схемы одинаково подходят для tool calling (каждый класс — инструмент с именем `action`) и для structured output (объединение по полю `action`).

## Действия
```python
from typing import Annotated, Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, Field, RootModel

class SearchFilters(BaseModel):
    types: list[RecordType] | None = None
    date_from: AwareDatetime | None = None
    date_to: AwareDatetime | None = None
    status: list[RecordStatus] | None = None

class CreateRecord(BaseModel):
    """Создать задачу, встречу или напоминание."""
    action: Literal["create_record"] = "create_record"
    type: RecordType
    title: str = Field(description="Суть без даты и времени: «позвонить Ивану»")
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    time_given: bool = Field(description="Пользователь назвал время, а не только дату")
    deadline: AwareDatetime | None = None

class ListRecords(BaseModel):
    """Показать записи за период: «что у меня сегодня», «на этой неделе»."""
    action: Literal["list_records"] = "list_records"
    date_from: AwareDatetime
    date_to: AwareDatetime
    types: list[RecordType] | None = None

class SearchRecords(BaseModel):
    """Найти старые записи по смыслу: «задачу про договор»."""
    action: Literal["search_records"] = "search_records"
    query: str = Field(description="О чём запись, без слов «найди», «когда-то»")
    filters: SearchFilters = SearchFilters()

class AskUser(BaseModel):
    """Спросить, если для действия не хватает данных."""
    action: Literal["ask_user"] = "ask_user"
    question: str
    missing: list[str] = Field(description="Каких полей не хватает: start, type …")

LLMAction = RootModel[Annotated[
    CreateRecord | ListRecords | SearchRecords | AskUser,
    Field(discriminator="action"),
]]
```

## Правила
- Даты — ISO 8601 со смещением. Время не названо (`time_given = False`) — код ставит `all_day` или задаёт вопрос, не полночь.
- Код проверяет: пояс есть, конец позже начала, при создании — не в прошлом. Ошибку проверки код возвращает LLM текстом.
- Несколько подходящих записей — код подбирает по точности (дата и время → время → название → нечёткое совпадение) и, если кандидатов несколько, просит выбрать из списка.
- Изменение, удаление, «выполнено» — бонус, добавляются позже действиями с целью:
```python
class TargetRef(BaseModel):
    record_id: UUID | None = None   # запись уже в фокусе разговора
    text: str | None = None         # «встречу с Иваном»
    when: AwareDatetime | None = None
```

## Результат действия
Что код возвращает после исполнения.
```python
class ActionResult(BaseModel):
    action: str
    ok: bool
    records: list[Record] = []       # созданная, найденные, за период
    conflicts: list[Record] = []     # пересечения по времени при создании встречи
    candidates: list[Record] = []    # несколько подходящих — нужен выбор
    missing: list[str] = []          # чего не хватило
    error: str | None = None
```
