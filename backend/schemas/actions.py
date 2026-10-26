"""Действия агента и результат их выполнения.

Контракт: docs/contracts/agent-tools.md. Менять только через техлида.
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, RootModel

from .record import Record, RecordStatus, RecordType

TYPES_HINT = (
    "«задачи» — task и reminder; «встречи» — meeting; «напоминания» — reminder; "
    "«дела», «планы», «что у меня» — null (все типы)"
)


class SearchFilters(BaseModel):
    types: list[RecordType] | None = Field(default=None, description=TYPES_HINT)
    date_from: AwareDatetime | None = Field(
        default=None,
        description="Необязательно. Начало периода, ISO 8601 со смещением: {ISO_EXAMPLE}",
    )
    date_to: AwareDatetime | None = Field(
        default=None,
        description="Необязательно. Конец периода, не включается, ISO 8601 со смещением: "
        "{ISO_EXAMPLE}",
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
        "{ISO_EXAMPLE}. «В N» без «утра», «вечера», «ночи»: 1–7 — N+12 («в 3» = 15:00), "
        "8–12 — как сказано. Утром 09:00, в обед 13:00, днём 15:00, вечером 18:00, "
        "ночью 22:00. Назван только день — начало этого дня и time_given=false. "
        "Дата не названа — null.",
    )
    end: AwareDatetime | None = Field(
        default=None,
        description="Конец, ISO 8601 со смещением пояса пользователя на эту дату: "
        "{ISO_EXAMPLE}. Не назван — null, не придумывать.",
    )
    time_given: bool = Field(
        description="true, только если время названо явно (в том числе «утром», «вечером»); "
        "false, если назван только день или дата не названа"
    )
    deadline: AwareDatetime | None = Field(
        default=None,
        description="Срок, ISO 8601 со смещением пояса пользователя на эту дату: "
        "{ISO_EXAMPLE}. «До конца недели» = воскресенье 23:59:59; «на следующей неделе» "
        "без дня = воскресенье следующей недели 23:59:59. Срока нет — null.",
    )


class ListRecords(BaseModel):
    """Показать записи за календарный интервал: «что у меня сегодня»,
    «планы на неделю», «какие у меня задачи». НЕ для поиска по теме."""

    action: Literal["list_records"] = "list_records"
    date_from: AwareDatetime = Field(
        description="Начало интервала, ISO 8601 со смещением: {ISO_EXAMPLE}. "
        "Период не назван — начало сегодняшнего дня."
    )
    date_to: AwareDatetime | None = Field(
        default=None,
        description="Конец интервала, не включается: «сегодня» — до 00:00 следующего дня. "
        "Период не назван («какие у меня задачи») — null. ISO 8601 со смещением: {ISO_EXAMPLE}",
    )
    types: list[RecordType] | None = Field(default=None, description=TYPES_HINT)


class SearchRecords(BaseModel):
    """Найти старые записи по смыслу: «задачу про договор»."""

    action: Literal["search_records"] = "search_records"
    query: str = Field(
        description="О чём запись, без слов «найди», «поищи», «задачу про», «когда-то»"
    )
    filters: SearchFilters = SearchFilters()


class TargetRef(BaseModel):
    """Какую запись менять. Заполняется одно: index, focus или text (+ when)."""

    index: int | None = Field(
        default=None,
        description="Номер записи из «Показано» в контексте, с 1: «вторую» = 2, "
        "«ту, что в пятницу» = номер записи на пятницу",
    )
    focus: bool = Field(
        default=False,
        description="true — запись «В фокусе»: «её», «эту», «нет, не в 15, а в 16» "
        "сразу после действия",
    )
    text: str | None = Field(
        default=None, description="Описание записи, если её нет в контексте: «встречу с Иваном»"
    )
    when: AwareDatetime | None = Field(
        default=None,
        description="Названная дата или время этой записи, ISO 8601 со смещением: {ISO_EXAMPLE}",
    )


class UpdateRecord(BaseModel):
    """Изменить запись: перенести, переименовать, поправить время.
    Заполняются только меняемые поля."""

    action: Literal["update_record"] = "update_record"
    target: TargetRef
    title: str | None = None
    start: AwareDatetime | None = Field(
        default=None,
        description="Новое начало, ISO 8601 со смещением: {ISO_EXAMPLE}. "
        "«Перенеси на пятницу» — новый день, время прежнее.",
    )
    end: AwareDatetime | None = None
    time_given: bool | None = None
    deadline: AwareDatetime | None = None
    replaces_last: bool = Field(
        default=False,
        description="true — «нет, не эту, а ту»: прошлое действие применено не к той записи",
    )


class SetStatus(BaseModel):
    """Отметить выполненной, отменить или вернуть в активные."""

    action: Literal["set_status"] = "set_status"
    target: TargetRef
    status: RecordStatus = Field(
        description="done — «выполнено», «я позвонил»; cancelled — «отмени»; "
        "active — «не выполнено», «верни»"
    )
    replaces_last: bool = Field(
        default=False,
        description="true — «нет, не эту, а ту»: прошлое действие применено не к той записи",
    )


class UndoLast(BaseModel):
    """Откатить последнее изменение: «верни как было», «верни»."""

    action: Literal["undo_last"] = "undo_last"


class AskUser(BaseModel):
    """Спросить, если для действия не хватает данных."""

    action: Literal["ask_user"] = "ask_user"
    question: str
    missing: list[str] = Field(description="Каких полей не хватает: start, type …")


class Help(BaseModel):
    """Реплика не про задачи и встречи или вопрос «что ты умеешь»."""

    action: Literal["help"] = "help"
    kind: Literal["help", "offtopic"]


LLMAction = RootModel[
    Annotated[
        CreateRecord
        | ListRecords
        | SearchRecords
        | UpdateRecord
        | SetStatus
        | UndoLast
        | AskUser
        | Help,
        Field(discriminator="action"),
    ]
]


class ActionResult(BaseModel):
    """Что код возвращает после исполнения действия."""

    action: str
    ok: bool
    records: list[Record] = []  # созданные, изменённые, найденные, за период
    conflicts: list[Record] = []  # пересечения по времени при создании и переносе встречи
    candidates: list[Record] = []  # несколько подходящих — нужен выбор
    restored: list[Record] = []  # откаченные при undo_last и replaces_last
    missing: list[str] = []  # чего не хватило
    error: str | None = None
