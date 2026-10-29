"""Чистые переходы состояния. Вызывающий загружает и сохраняет состояние один раз."""

import re
import unicodedata
from copy import deepcopy
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from schemas import (
    ActionResult,
    AskUser,
    ConversationState,
    CreateRecord,
    LastAction,
    LLMAction,
    RecordType,
    SetStatus,
    TargetRef,
    UpdateRecord,
)

MUTATIONS = {"create_record", "update_record", "set_status"}
LIST_ACTIONS = {"list_records", "search_records"}
REFUSALS = {"не надо", "забудь", "отмена", "проехали", "забей", "неважно", "отбой", "стоп"}
# Ждём выбора записи из кандидатов: одной (`choice`) или подтверждения всех (`confirm`).
CHOOSING = {"choice", "confirm"}
NUMBER = re.compile(r"номер (\d{1,3})")


def _normalized(text: str) -> str:
    """Без регистра и знаков препинания, пробелы схлопнуты: «Номер 2.» → «номер 2»."""
    text = "".join(
        " " if unicodedata.category(char).startswith("P") else char
        for char in unicodedata.normalize("NFKC", text).casefold()
    )
    return " ".join(text.split())


def is_refusal(text: str, state: ConversationState) -> bool:
    if state.awaiting is None:
        return False
    return _normalized(text) in REFUSALS


def chosen_number(text: str, state: ConversationState) -> int | None:
    """«номер N» в ответ на выбор или подтверждение — N, иначе `None`.

    Так отвечает чип «номер N» (api.md, «Правила»); разбирает код, без модели: нажатие должно
    срабатывать всегда и сразу. Диапазон N проверяет вызывающий.
    """
    if state.awaiting not in CHOOSING or not state.candidates or state.pending is None:
        return None
    if not isinstance(state.pending.root, UpdateRecord | SetStatus):
        return None
    match = NUMBER.fullmatch(_normalized(text))
    return int(match.group(1)) if match else None


def choose_candidate(state: ConversationState, number: int) -> UpdateRecord | SetStatus:
    """Отложенное действие (`pending`) над N-й записью из кандидатов — как если бы модель
    вернула «вторую» (`TargetRef(index=N)`). Номер — N-я запись `candidates`, как в чипе."""
    return state.pending.root.model_copy(update={"target": TargetRef(index=number)}, deep=True)


def asks_meeting_time(state: ConversationState) -> bool:
    """Ждём время встречи, у которой день уже известен (`awaiting = "time"`).

    - Черновик — `CreateRecord` встречи с днём без времени (`time_given = False`), а сервис
      ответил `missing = ["start"]` («Не названо время встречи»).
    - Или вопрос модели с черновиком (`AskUser.draft`): встреча, день есть, времени нет
      (ни `time_given`, ни отдельного `time`), в `missing` — `start` или `time`.
    Встреча без дня («в 14:45, а когда?») — обычный вопрос (`answer`): спрашиваем день.
    """
    if state.pending is None:
        return False
    pending = state.pending.root
    if isinstance(pending, CreateRecord):
        return (
            "start" in state.missing
            and pending.type == RecordType.MEETING
            and pending.start is not None
            and not pending.time_given
        )
    if isinstance(pending, AskUser) and pending.draft is not None:
        draft = pending.draft
        return (
            bool({"start", "time"} & set(state.missing))
            and draft.type == RecordType.MEETING
            and draft.start is not None
            and not draft.time_given
            and draft.time is None
        )
    return False


def reset_pending(state: ConversationState) -> ConversationState:
    new = state.model_copy(deep=True)
    new.pending = None
    new.pending_skipped = False
    new.candidates = []
    new.missing = []
    new.awaiting = None
    return new


def pending_draft(state: ConversationState) -> AskUser | None:
    """Вопрос с частичным черновиком создания (AskUser.draft), если ассистент его ждёт."""
    if state.pending is not None and isinstance(state.pending.root, AskUser):
        return state.pending.root if state.pending.root.draft is not None else None
    return None


def complete_from_draft(
    ask: AskUser, action: CreateRecord, timezone_name: str = "UTC"
) -> CreateRecord:
    """Дополнить ответ уже названным: недостающие поля — из ответа, остальное — из draft.

    «Напомни завтра в 10» → «Позвонить маме»: тип и время из draft, суть из ответа.
    «Встреча с Сергеем в 14:45» → «Завтра»: день из ответа, время draft.time.
    """
    draft = ask.draft
    missing = set(ask.missing)
    data = action.model_dump()
    known = draft.model_dump(exclude_none=True)
    time = known.pop("time", None)
    start_missing = "start" in missing
    for field, value in known.items():
        answered = data.get(field) is not None
        if field in ("start", "time_given") and start_missing and data.get("start") is not None:
            continue  # день и время ответа важнее
        if field in missing and answered:
            continue
        data[field] = value
    start = data.get("start")
    if time is not None and start is not None and not data.get("time_given"):
        hour, minute = map(int, time.split(":"))
        day = start.astimezone(ZoneInfo(timezone_name))  # день ответа в поясе пользователя
        data["start"] = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        data["time_given"] = True
    return CreateRecord.model_validate(data)


def continues_pending(state: ConversationState, action: BaseModel) -> bool:
    if state.pending is None:
        return False
    if isinstance(action, AskUser):
        return True
    pending = state.pending.root
    if isinstance(pending, AskUser):
        return isinstance(action, CreateRecord)
    if isinstance(pending, CreateRecord):
        return isinstance(action, CreateRecord) and pending.type == action.type
    return pending.action == action.action


def focus_record_id(result: ActionResult) -> UUID | None:
    if not result.ok:
        return None
    if result.action in LIST_ACTIONS | MUTATIONS:
        records = result.records
    elif result.action == "undo_last":
        records = result.restored
    else:
        return None
    return records[0].id if len(records) == 1 else None


def update_state(
    state: ConversationState,
    action: BaseModel,
    result: ActionResult | None,
    *,
    before: list[dict[str, Any]] | None = None,
) -> ConversationState:
    """Вернуть новое состояние, не меняя входы и не обращаясь к БД.

    action — конкретная модель действия (или LLMAction); result=None только для AskUser.
    before — снимки записей ДО update_record/set_status, в порядке result.records.
    `shown` — все записи ответа (или кандидаты) без группировки: номер N — `shown[N-1]`.
    """
    if isinstance(action, LLMAction):
        action = action.root
    new = state.model_copy(deep=True)
    continuing = continues_pending(state, action)
    choosing = state.awaiting in CHOOSING and continuing

    if new.pending is not None:
        if continuing:
            new.pending_skipped = False
        elif isinstance(action, CreateRecord) or new.pending_skipped:
            new = reset_pending(new)
        else:
            new.pending_skipped = True

    if isinstance(action, AskUser):
        asking = new.pending is None or isinstance(new.pending.root, AskUser)
        if asking and action.draft is not None and action.draft.model_dump(exclude_none=True):
            # Черновик создания хранится в pending как сам вопрос; повторный вопрос дополняет его.
            previous = pending_draft(new)
            draft = action.draft
            if previous is not None:
                draft = previous.draft.model_copy(
                    update=action.draft.model_dump(exclude_none=True)
                )
            new.pending = LLMAction(action.model_copy(update={"draft": draft}, deep=True))
        if asking:
            new.missing = list(action.missing)
        if new.awaiting not in CHOOSING:
            new.awaiting = "time" if asks_meeting_time(new) else "answer"
        return new
    if result is None:
        raise ValueError("Для исполняемого действия нужен ActionResult")

    # replaces_last может уже откатить прошлое действие до уточнения новой цели.
    if result.restored:
        new.last_action = None
    if result.candidates:
        new.pending = LLMAction(action.model_copy(deep=True))
        new.pending_skipped = False
        new.candidates = [record.id for record in result.candidates]
        new.shown = list(new.candidates)
        new.focus_record_id = None
        new.missing = []
        # Массовое действие («отмени всё на завтра») спрашивает подтверждение всех кандидатов,
        # остальное — выбор одной записи.
        mass = isinstance(action, SetStatus) and action.target.all
        new.awaiting = "confirm" if mass else "choice"
        return new
    if not result.ok:
        if result.missing:
            new.pending = LLMAction(action.model_copy(deep=True))
            new.pending_skipped = False
            new.missing = list(result.missing)
            new.candidates = []
            new.awaiting = "time" if asks_meeting_time(new) else "answer"
        return new

    if continuing or new.pending is None:
        new = reset_pending(new)
    if result.action in LIST_ACTIONS:
        # Номера на экране — все записи ответа в том же порядке, без группировки (api.md)
        new.shown = [record.id for record in result.records]
    elif choosing:
        new.shown = [record.id for record in result.records]
    if result.action in MUTATIONS | LIST_ACTIONS | {"undo_last"}:
        new.focus_record_id = focus_record_id(result)
    if result.action in MUTATIONS and result.records:
        new.last_action = LastAction(
            action=result.action,
            record_ids=[record.id for record in result.records],
            before=deepcopy(before or []) if result.action != "create_record" else [],
        )
    elif result.action == "undo_last":
        new.last_action = None
    return new
