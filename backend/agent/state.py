"""Чистые переходы состояния. Вызывающий загружает и сохраняет состояние один раз."""

import unicodedata
from copy import deepcopy
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from schemas import ActionResult, AskUser, ConversationState, CreateRecord, LastAction, LLMAction

MUTATIONS = {"create_record", "update_record", "set_status"}
LIST_ACTIONS = {"list_records", "search_records"}
REFUSALS = {"не надо", "забудь", "отмена", "проехали", "забей", "неважно", "отбой", "стоп"}


def is_refusal(text: str, state: ConversationState) -> bool:
    if state.awaiting is None:
        return False
    normalized = "".join(
        " " if unicodedata.category(char).startswith("P") else char
        for char in unicodedata.normalize("NFKC", text).casefold()
    )
    return " ".join(normalized.split()) in REFUSALS


def reset_pending(state: ConversationState) -> ConversationState:
    new = state.model_copy(deep=True)
    new.pending = None
    new.pending_skipped = False
    new.candidates = []
    new.missing = []
    new.awaiting = None
    return new


def continues_pending(state: ConversationState, action: BaseModel) -> bool:
    if state.pending is None:
        return False
    if isinstance(action, AskUser):
        return True
    pending = state.pending.root
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
    choosing = state.awaiting == "choice" and continuing

    if new.pending is not None:
        if continuing:
            new.pending_skipped = False
        elif isinstance(action, CreateRecord) or new.pending_skipped:
            new = reset_pending(new)
        else:
            new.pending_skipped = True

    if isinstance(action, AskUser):
        if new.pending is None:
            new.missing = list(action.missing)
        if new.awaiting != "choice":
            new.awaiting = "answer"
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
        new.awaiting = "choice"
        return new
    if not result.ok:
        if result.missing:
            new.pending = LLMAction(action.model_copy(deep=True))
            new.pending_skipped = False
            new.missing = list(result.missing)
            new.candidates = []
            new.awaiting = "answer"
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
