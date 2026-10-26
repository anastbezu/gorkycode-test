# Контракт: действия агента

Граница: LLM ↔ агент (Илья, Давид) ↔ сервисы (Денис). Pydantic v2, типы записи и состояние разговора — `data-model.md`.

Один вызов LLM на реплику: LLM возвращает действие с аргументами, код его исполняет. Схемы одинаково подходят для tool calling (каждый класс — инструмент с именем `action`) и для structured output (объединение по полю `action`).

## Действия
```python
from typing import Annotated, Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, Field, RootModel

TYPES_HINT = ("«задачи» — task и reminder; «встречи» — meeting; «напоминания» — reminder; "
              "«дела», «планы», «что у меня» — null (все типы)")

class SearchFilters(BaseModel):
    types: list[RecordType] | None = Field(default=None, description=TYPES_HINT)
    date_from: AwareDatetime | None = Field(default=None, description="Необязательно. Начало периода, ISO 8601 со смещением: {ISO_EXAMPLE}")
    date_to: AwareDatetime | None = Field(default=None, description="Необязательно. Конец периода, не включается, ISO 8601 со смещением: {ISO_EXAMPLE}")
    status: list[RecordStatus] | None = None

class CreateRecord(BaseModel):
    """Создать задачу, встречу или напоминание."""
    action: Literal["create_record"] = "create_record"
    type: RecordType
    title: str = Field(description="Суть без командных слов («напомни», «поставь»), даты и времени: «позвонить Ивану»")
    start: AwareDatetime | None = Field(default=None, description="Начало, ISO 8601 со смещением пояса пользователя на эту дату: {ISO_EXAMPLE}. Время по правилам времени (раздел «Правила»). Назван только день — начало этого дня и time_given=false. Дата не названа — null.")
    end: AwareDatetime | None = Field(default=None, description="Конец, ISO 8601 со смещением пояса пользователя на эту дату: {ISO_EXAMPLE}. Не назван — null, не придумывать.")
    time_given: bool = Field(description="true, только если время названо явно (в том числе «утром», «вечером»); false, если назван только день или дата не названа")
    deadline: AwareDatetime | None = Field(default=None, description="Срок, ISO 8601 со смещением пояса пользователя на эту дату: {ISO_EXAMPLE}. «До конца недели» = воскресенье 23:59:59; «на следующей неделе» без дня = воскресенье следующей недели 23:59:59. Срока нет — null.")

class ListRecords(BaseModel):
    """Показать записи за календарный интервал: «что у меня сегодня», «планы на неделю», «какие у меня задачи». НЕ для поиска по теме."""
    action: Literal["list_records"] = "list_records"
    date_from: AwareDatetime = Field(description="Начало интервала, ISO 8601 со смещением: {ISO_EXAMPLE}. Период не назван — начало сегодняшнего дня.")
    date_to: AwareDatetime | None = Field(default=None, description="Конец интервала, не включается: «сегодня» — до 00:00 следующего дня. Период не назван («какие у меня задачи») — null. ISO 8601 со смещением: {ISO_EXAMPLE}")
    types: list[RecordType] | None = Field(default=None, description=TYPES_HINT)

class SearchRecords(BaseModel):
    """Найти старые записи по смыслу: «задачу про договор»."""
    action: Literal["search_records"] = "search_records"
    query: str = Field(description="О чём запись, без слов «найди», «поищи», «задачу про», «когда-то»")
    filters: SearchFilters = SearchFilters()

class TargetRef(BaseModel):
    """Какую запись менять. Заполняется одно: index, focus или text (+ when, filters); all — для нескольких."""
    index: int | None = Field(default=None, description="Номер записи из «Показано» в контексте, с 1: «вторую» = 2, «ту, что в пятницу» = номер записи на пятницу")
    focus: bool = Field(default=False, description="true — запись «В фокусе»: «её», «эту», «нет, не в 15, а в 16» сразу после действия")
    text: str | None = Field(default=None, description="Описание записи, если её нет в контексте: «встречу с Иваном»")
    when: AwareDatetime | None = Field(default=None, description="Названная дата или время этой записи, ISO 8601 со смещением: {ISO_EXAMPLE}")
    filters: SearchFilters | None = Field(default=None, description="Тип и период для нескольких записей: «все созвоны» — types=[meeting], text «созвон»; «всё на завтра» — период завтрашнего дня")
    all: bool = Field(default=False, description="true — все подходящие записи: «отмени все созвоны», «отмени всё на завтра»; «да» на вопрос «отменить все?» — все из «Показано»")

class UpdateRecord(BaseModel):
    """Изменить запись: перенести, переименовать, поправить время. Заполняются только меняемые поля."""
    action: Literal["update_record"] = "update_record"
    target: TargetRef
    title: str | None = None
    start: AwareDatetime | None = Field(default=None, description="Новое начало, ISO 8601 со смещением: {ISO_EXAMPLE}. «Перенеси на пятницу» — новый день, время прежнее.")
    end: AwareDatetime | None = None
    time_given: bool | None = None
    deadline: AwareDatetime | None = None
    replaces_last: bool = Field(default=False, description="true — «нет, не эту, а ту»: прошлое действие применено не к той записи")

class SetStatus(BaseModel):
    """Отметить выполненной, отменить или вернуть в активные."""
    action: Literal["set_status"] = "set_status"
    target: TargetRef
    status: RecordStatus = Field(description="done — «выполнено», «я позвонил»; cancelled — «отмени»; active — «не выполнено», «верни»")
    replaces_last: bool = Field(default=False, description="true — «нет, не эту, а ту»: прошлое действие применено не к той записи")

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

LLMAction = RootModel[Annotated[
    CreateRecord | ListRecords | SearchRecords | UpdateRecord | SetStatus | UndoLast | AskUser | Help,
    Field(discriminator="action"),
]]
```

## Правила
**Даты и время**
- Даты — ISO 8601 со смещением. `{ISO_EXAMPLE}` в описаниях агент заменяет примером в поясе пользователя (`2026-10-25T15:00:00+03:00` для Europe/Moscow).
- «В N» без «утра», «вечера», «ночи»: часы 1–7 — это N+12 («в 3» = 15:00, «без пятнадцати три» = 14:45), 8–12 — как сказано. Явное «утра», «ночи», «вечера» сильнее правила.
- Части дня при создании: утром — 09:00, в обед — 13:00, днём — 15:00, вечером — 18:00, ночью — 22:00. В вопросе о периоде — интервал: «что у меня вечером» = [18:00, 24:00).
- «В пятницу» — ближайшая пятница впереди; сегодня пятница — через неделю. «В следующую пятницу» — пятница следующей недели.
- «Эта неделя» — с понедельника 00:00 до следующего понедельника 00:00; «следующая неделя» — следующие семь дней с понедельника.
- Период без дня для задачи: «на следующей неделе» — срок, воскресенье следующей недели 23:59:59, без начала; «на выходных» — суббота, весь день; «в конце месяца» — последний день месяца, весь день.
- Период — `[date_from, date_to)`: `date_to` не включается. «Сегодня» — с 00:00 сегодня до 00:00 завтра; запись «на весь день» завтра (`start` = 00:00 завтра) в него не попадает. `date_to = None` — без конца периода, и в конец добавляются активные записи без даты.
- Назван только день (`time_given = False`, `start` — начало дня): задача и напоминание сохраняются с `all_day`, для встречи код возвращает `missing=["start"]` — агент спрашивает время. Дата не названа — `start = None`; задача и напоминание сохраняются без даты, без вопроса.

**Проверки кода**
- Пояс есть, конец позже начала, при создании и переносе — не в прошлом (для `all_day` — по дате, запись на сегодня допустима). Ошибку проверки код возвращает LLM текстом.
- Конфликт: при создании и переносе встречи код ищет другие активные встречи, пересекающиеся по времени; встрече без `end` для проверки даётся 60 минут (в запись не пишется). Запись сохраняется, пересечения — в `ActionResult.conflicts`.
- Точный дубль — активная запись с тем же названием и тем же `start` — не создаётся: `ok=False`, `error`, существующая запись в `records`.

**Цель изменения**
- `TargetRef` переводит в id код: `index` — запись из `shown`, `focus` — `focus_record_id`, `text` и `when` — поиск среди активных записей пользователя, будущие в приоритете. Идентификаторы модель не передаёт.
- Несколько подходящих записей — код подбирает по точности (дата и время → время → название → нечёткое совпадение) и, если кандидатов несколько, ничего не меняет, а возвращает `candidates` для выбора.
- `replaces_last = True`: код откатывает `last_action` (`data-model.md`) и применяет действие к новой цели; откаченные записи — в `ActionResult.restored`.
- `undo_last`: создание откатывается отменой созданной записи, изменение и смена статуса — прежними значениями из `last_action.before`.
- Несколько записей одной командой (`all = True`, только `set_status`): код находит все подходящие активные записи по `text`, `when`, `filters` (не больше 20; больше — просит сузить) и ничего не меняет, а возвращает их в `candidates` и спрашивает подтверждение («Отменить 5 созвонов: …?»). Ответ «да», «все» — `set_status` с `all = True` без описания: код применяет его ко всем записям из `shown`. Подходит одна запись — исполняется сразу, без подтверждения. `last_action` хранит все записи и их прежние статусы — «верни» откатывает всё разом.

**Несколько действий**
- Если LLM вернула несколько вызовов `create_record` (не больше трёх) — код исполняет все и даёт один ответ; `ActionResult.records` — все созданные. Любое другое сочетание — исполняется первый вызов, ответ говорит, что остальное нужно сказать отдельно.

## Результат действия
Что код возвращает после исполнения.
```python
class ActionResult(BaseModel):
    action: str
    ok: bool
    records: list[Record] = []       # созданные, изменённые, найденные, за период
    conflicts: list[Record] = []     # пересечения по времени при создании и переносе встречи
    candidates: list[Record] = []    # несколько подходящих — нужен выбор
    restored: list[Record] = []      # откаченные при undo_last и replaces_last
    missing: list[str] = []          # чего не хватило
    error: str | None = None
```
