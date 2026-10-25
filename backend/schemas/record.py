"""Запись: задача, встреча или напоминание.

Контракт: docs/contracts/data-model.md. Менять только через техлида.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator


class RecordType(StrEnum):
    TASK = "task"
    MEETING = "meeting"
    REMINDER = "reminder"


class RecordStatus(StrEnum):
    ACTIVE = "active"
    DONE = "done"
    CANCELLED = "cancelled"


class Record(BaseModel):
    # from_attributes: можно собрать из строки SQLAlchemy — Record.model_validate(row)
    model_config = ConfigDict(from_attributes=True)

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
