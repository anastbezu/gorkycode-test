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
- Дата без времени — `all_day = True`, `start` — начало этого дня в поясе пользователя. При `all_day` время в `start` не показывается и не считается временем события.
- Дата не названа — `start = None`.
- Проверка «не в прошлом» для записи `all_day` — по дате в поясе пользователя: запись на сегодня допустима.
- `start` и `deadline` — разные поля.
- У каждой записи есть пользователь: учётка или гость (анонимный идентификатор браузера), `api.md`. Гость и новая учётка начинают без записей, датасет — только у демо-учёток.
- Повторы в MVP не входят.
- Список за период не показывает отменённые записи (`cancelled`); остальные статусы показываются.

## Состояние разговора
Хранится на сервере, в той же базе.
```python
class LastAction(BaseModel):
    action: str                  # create_record, update_record, set_status
    record_ids: list[UUID]       # какие записи затронуты
    before: list[dict] = []      # прежние значения изменённых полей, по одной записи на элемент;
                                 # у создания — пусто

class ConversationState(BaseModel):
    conversation_id: UUID
    user_id: UUID
    focus_record_id: UUID | None = None   # «её», «эту встречу»
    shown: list[UUID] = []                # записи под номерами на экране, в том же порядке
    last_action: LastAction | None = None # последнее изменение — для поправки и отката
    pending: "LLMAction | None" = None    # действие ждёт недостающих полей (agent-tools.md)
    pending_skipped: bool = False         # прошлая реплика была не про черновик
    candidates: list[UUID] = []           # ждём выбора из нескольких записей
    missing: list[str] = []               # каких полей не хватает для pending
    awaiting: Literal["answer", "choice", "confirm", "time"] | None = None  # чего ждёт ассистент (api.md, «Правила»)
```

### Правила состояния
- LLM получает состояние не целиком, а коротким текстом в системном промпте: показанные записи под номерами (не больше 10), последнее действие, черновик и чего в нём не хватает. Идентификаторы в текст не попадают — модель ссылается на запись номером или фокусом (`TargetRef`, `agent-tools.md`), код переводит ссылку в id.
- `shown` перезаписывается каждым списком, поиском и выбором из кандидатов — всеми записями, которые интерфейс показывает под номерами (`api.md`): `ActionResult.candidates`, если они не пустые, иначе `ActionResult.records`, в том же порядке. Номер N — запись `shown[N - 1]`, в том числе дальше десятого, хотя в промпт попадают первые 10. Текст ответа может назвать не все записи и свернуть одинаковые («созвон с Севером — 7 раз»): на `shown` и номера это не влияет. Если текст называет номера («1) завтра в 15:00; 2) …»), они совпадают с номерами на экране.
- `focus_record_id` — запись, если создана, изменена или показана ровно одна. Показано несколько — фокус снимается, «её» ведёт к выбору из `shown`.
- `last_action` перезаписывается каждым изменяющим действием (создание, изменение, смена статуса) и нужен для поправки («нет, не в 15, а в 16»), отката («верни») и замены цели («не эту, а ту»).
- Черновик при смене темы: реплика не про черновик выполняется, черновик остаётся, `pending_skipped = True`, ответ напоминает о черновике. Следующая реплика снова не про черновик или новое создание сбрасывают черновик.
- Отказ, пока ассистент ждёт ответа или выбора («не надо», «забудь», «отмена», «проехали», «забей», «неважно», «отбой», «стоп», «передумал», «я передумал», «не надо наверное»; на подтверждение «Отменить N …?» — ещё «нет»): реплика целиком совпадает с фразой отказа — код сбрасывает черновик и кандидатов без вызова LLM. «Нет, в 16» в уточнении — не отказ, а ответ. «Отмени встречу» — не отказ, а команда.
