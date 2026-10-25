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
    date_from: AwareDatetime | None = Field(default=None, description="Необязательно. Начало периода, ISO 8601 со смещением: {ISO_EXAMPLE}")
    date_to: AwareDatetime | None = Field(default=None, description="Необязательно. Конец периода, не включается, ISO 8601 со смещением: {ISO_EXAMPLE}")
    status: list[RecordStatus] | None = None

class CreateRecord(BaseModel):
    """Создать задачу, встречу или напоминание."""
    action: Literal["create_record"] = "create_record"
    type: RecordType
    title: str = Field(description="Суть без командных слов («напомни», «поставь»), даты и времени: «позвонить Ивану»")
    start: AwareDatetime | None = Field(default=None, description="Начало, ISO 8601 со смещением пояса пользователя на эту дату: {ISO_EXAMPLE}. «Утром» = 09:00, «в N» = N:00. Назван только день — начало этого дня и time_given=false. Дата не названа — null.")
    end: AwareDatetime | None = Field(default=None, description="Конец, ISO 8601 со смещением пояса пользователя на эту дату: {ISO_EXAMPLE}. Не назван — null, не придумывать.")
    time_given: bool = Field(description="true, только если время названо явно (в том числе «утром»); false, если назван только день или дата не названа")
    deadline: AwareDatetime | None = Field(default=None, description="Срок, ISO 8601 со смещением пояса пользователя на эту дату: {ISO_EXAMPLE}. «До конца недели» = воскресенье 23:59:59. Срока нет — null.")

class ListRecords(BaseModel):
    """Показать записи за явный календарный интервал: «что у меня сегодня», «планы на неделю». НЕ для поиска по теме."""
    action: Literal["list_records"] = "list_records"
    date_from: AwareDatetime = Field(description="Начало интервала, ISO 8601 со смещением: {ISO_EXAMPLE}")
    date_to: AwareDatetime = Field(description="Конец интервала, не включается: «сегодня» — до 00:00 следующего дня. ISO 8601 со смещением: {ISO_EXAMPLE}")
    types: list[RecordType] | None = None

class SearchRecords(BaseModel):
    """Найти старые записи по смыслу: «задачу про договор»."""
    action: Literal["search_records"] = "search_records"
    query: str = Field(description="О чём запись, без слов «найди», «поищи», «задачу про», «когда-то»")
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
- Даты — ISO 8601 со смещением. `{ISO_EXAMPLE}` в описаниях агент заменяет примером в поясе пользователя (`2026-10-25T15:00:00+03:00` для Europe/Moscow).
- Период — `[date_from, date_to)`: `date_to` не включается. «Сегодня» — с 00:00 сегодня до 00:00 завтра; запись «на весь день» завтра (`start` = 00:00 завтра) в него не попадает.
- Назван только день (`time_given = False`, `start` — начало дня): задача и напоминание сохраняются с `all_day`, для встречи код возвращает `missing=["start"]` — агент спрашивает время. Дата не названа — `start = None`.
- Код проверяет: пояс есть, конец позже начала, при создании — не в прошлом (для `all_day` — по дате, запись на сегодня допустима). Ошибку проверки код возвращает LLM текстом.
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
