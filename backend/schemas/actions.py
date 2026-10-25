"""Действия агента и результат их выполнения.

Контракт: docs/contracts/agent-tools.md. Менять только через техлида.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, RootModel

from .record import Record, RecordStatus, RecordType


class SearchFilters(BaseModel):
    types: list[RecordType] | None = None
    date_from: AwareDatetime | None = Field(
        default=None,
        description="Необязательно. Начало периода, ISO 8601 со смещением: {ISO_EXAMPLE}",
    )
    date_to: AwareDatetime | None = Field(
        default=None,
        description="Необязательно. Конец периода, ISO 8601 со смещением: {ISO_EXAMPLE}",
    )
    status: list[RecordStatus] | None = None


class CreateRecord(BaseModel):
    """Создать задачу, встречу или напоминание."""

    action: Literal["create_record"] = "create_record"
    type: RecordType
    title: str = Field(
        description="Суть без командных слов («напомни», «поставь»), даты и времени: "
        "«позвонить Ивану»"
    )
    start: AwareDatetime | None = Field(
        default=None,
        description="Начало, ISO 8601 со смещением пояса пользователя на эту дату: "
        "{ISO_EXAMPLE}. «Утром» = 09:00, «в N» = N:00. Назван только день — начало "
        "этого дня и time_given=false. Дата не названа — null.",
    )
    end: AwareDatetime | None = Field(
        default=None,
        description="Конец, ISO 8601 со смещением пояса пользователя на эту дату: "
        "{ISO_EXAMPLE}. Не назван — null, не придумывать.",
    )
    time_given: bool = Field(
        description="true, только если время названо явно (в том числе «утром»); "
        "false, если назван только день или дата не названа"
    )
    deadline: AwareDatetime | None = Field(
        default=None,
        description="Срок, ISO 8601 со смещением пояса пользователя на эту дату: "
        "{ISO_EXAMPLE}. «До конца недели» = воскресенье 23:59:59. Срока нет — null.",
    )


class ListRecords(BaseModel):
    """Показать записи за явный календарный интервал: «что у меня сегодня»,
    «планы на неделю». НЕ для поиска по теме."""

    action: Literal["list_records"] = "list_records"
    date_from: AwareDatetime = Field(
        description="Начало интервала, ISO 8601 со смещением: {ISO_EXAMPLE}"
    )
    date_to: AwareDatetime = Field(
        description="Конец интервала, ISO 8601 со смещением: {ISO_EXAMPLE}"
    )
    types: list[RecordType] | None = None


class SearchRecords(BaseModel):
    """Найти старые записи по смыслу: «задачу про договор»."""

    action: Literal["search_records"] = "search_records"
    query: str = Field(
        description="О чём запись, без слов «найди», «поищи», «задачу про», «когда-то»"
    )
    filters: SearchFilters = SearchFilters()


class AskUser(BaseModel):
    """Спросить, если для действия не хватает данных."""

    action: Literal["ask_user"] = "ask_user"
    question: str
    missing: list[str] = Field(description="Каких полей не хватает: start, type …")


LLMAction = RootModel[
    Annotated[
        CreateRecord | ListRecords | SearchRecords | AskUser,
        Field(discriminator="action"),
    ]
]


class TargetRef(BaseModel):
    """Цель для изменения / удаления / «выполнено» (бонус)."""

    record_id: UUID | None = None   # запись уже в фокусе разговора
    text: str | None = None         # «встречу с Иваном»
    when: AwareDatetime | None = None


class ActionResult(BaseModel):
    """Что код возвращает после исполнения действия."""

    action: str
    ok: bool
    records: list[Record] = []       # созданная, найденные, за период
    conflicts: list[Record] = []     # пересечения по времени при создании встречи
    candidates: list[Record] = []    # несколько подходящих — нужен выбор
    missing: list[str] = []          # чего не хватило
    error: str | None = None
