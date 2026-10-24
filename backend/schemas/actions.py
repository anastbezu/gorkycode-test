"""Действия агента и результат их выполнения.

Контракт: docs/contracts/agent-tools.md. Менять только через техлида.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, RootModel

from .record import Record, RecordStatus, RecordType


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
