"""Записи из интерфейса — тела запросов кнопок `/api/items`.

Контракт: docs/contracts/api.md, «Записи из интерфейса». Менять только через техлида.
"""

from pydantic import AwareDatetime, BaseModel, Field

from .record import RecordStatus, RecordType


class CreateItem(BaseModel):
    type: RecordType
    title: str = Field(min_length=1)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None  # только у встречи
    time_given: bool = True  # false — «весь день»: start — начало дня
    deadline: AwareDatetime | None = None


class UpdateItem(BaseModel):  # передаются только меняемые поля
    title: str | None = None
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    time_given: bool | None = None
    deadline: AwareDatetime | None = None


class SetItemStatus(BaseModel):
    status: RecordStatus  # done — «выполнено»; cancelled — «удалить»; active — «вернуть»
