# TODO: replace with contract models

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, RootModel, model_validator


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


class ActionResult(BaseModel):
    action: str
    ok: bool
    records: list[Record] = []       # созданная, найденные, за период
    conflicts: list[Record] = []     # пересечения по времени при создании встречи
    candidates: list[Record] = []    # несколько подходящих — нужен выбор
    missing: list[str] = []          # чего не хватило
    error: str | None = None

# TODO: replace with backend/schemas
class LLMConfig(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None