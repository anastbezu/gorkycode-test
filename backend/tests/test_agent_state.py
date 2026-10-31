"""Переходы agent-06 и интерфейс, который вызывает agent-07."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.context import build_state_context
from agent.list_replies import reply_for_list
from agent.presentation import group_records
from agent.search_replies import reply_for_search
from agent.state import is_refusal, reset_pending, update_state
from schemas import (
    ActionResult,
    AskUser,
    ConversationState,
    CreateRecord,
    Help,
    LastAction,
    ListRecords,
    LLMAction,
    Record,
    SearchRecords,
    SetStatus,
    TargetRef,
    UndoLast,
    UpdateRecord,
)

NOW = datetime(2030, 1, 1, 10, tzinfo=UTC)


@pytest.fixture
def state():
    return ConversationState(conversation_id=uuid4(), user_id=uuid4())


def record(state, title="Договор", **fields):
    return Record(id=uuid4(), user_id=state.user_id, type="task", title=title,
                  created_at=NOW, **fields)


def draft(state):
    return state.model_copy(update={
        "pending": LLMAction(CreateRecord(type="meeting", title="Команда", time_given=False)),
        "missing": ["start"], "awaiting": "answer",
    })


@pytest.mark.parametrize("phrase", [
    "Не надо!!!", " ЗАБУДЬ… ", "Отмена", "проехали", "забей", "неважно", "отбой", "стоп",
    "НЕ\tНАДО", "«не надо»", "не, надо", "Передумал", "я передумал.", "не надо, наверное",
])
def test_refusal_matches_whole_normalized_phrase_only(state, phrase):
    assert is_refusal(phrase, draft(state))
    assert not is_refusal(phrase, state)


@pytest.mark.parametrize("phrase", ["Отмени встречу с Иваном", "не надо отменять", "стоп кран"])
def test_commands_are_not_refusals(state, phrase):
    assert not is_refusal(phrase, draft(state))


def test_no_refuses_only_confirmation(state):
    confirm = state.model_copy(update={"candidates": [uuid4()], "awaiting": "confirm"})
    assert is_refusal("Нет.", confirm)
    assert not is_refusal("нет", draft(state))
    assert not is_refusal("нет, в 16", confirm)


def test_reset_preserves_history_and_leaves_input_unchanged(state):
    old = draft(state)
    old.pending_skipped = True
    old.candidates = [uuid4()]
    old.shown = [uuid4()]
    old.focus_record_id = uuid4()
    old.last_action = LastAction(action="create_record", record_ids=[old.focus_record_id])
    new = reset_pending(old)
    assert new.pending is None and new.awaiting is None and not new.pending_skipped
    assert new.missing == new.candidates == []
    assert (new.shown, new.last_action, new.focus_record_id) == (
        old.shown, old.last_action, old.focus_record_id,
    )
    assert old.pending is not None and old.pending_skipped and old.candidates


@pytest.mark.parametrize("action", [SearchRecords(query="договор"), Help(kind="offtopic")])
def test_first_detour_keeps_draft_second_clears_it(state, action):
    old = draft(state)
    result = ActionResult(action=action.action, ok=True)
    first = update_state(old, action, result)
    assert first.pending == old.pending and first.pending_skipped
    assert first.awaiting == "answer"
    second = update_state(first, action, result)
    assert second.pending is None and not second.pending_skipped and second.awaiting is None
    assert old.pending is not None and not old.pending_skipped


def test_question_resumes_draft_and_does_not_erase_candidate_choice(state):
    old = draft(state)
    old.pending_skipped = True
    question = AskUser(question="Во сколько?", missing=["start"])
    updated = update_state(old, question, None)
    assert updated.pending == old.pending and not updated.pending_skipped
    old.awaiting = "choice"
    old.candidates = [uuid4()]
    updated = update_state(old, question, None)
    assert updated.awaiting == "choice" and updated.candidates == old.candidates


def test_new_type_discards_old_draft_even_when_execution_fails(state):
    action = CreateRecord(type="task", title="Хлеб", time_given=False)
    new = update_state(draft(state), action, ActionResult(action=action.action, ok=False))
    assert new.pending is None and new.awaiting is None


@pytest.mark.parametrize("count", [1, 2])
def test_creation_remembers_all_ids_and_clears_completed_draft(state, count):
    old = draft(state)
    records = [record(state, str(i)) for i in range(count)]
    new = update_state(old, old.pending.root, ActionResult(
        action="create_record", ok=True, records=records,
    ))
    assert new.last_action.record_ids == [r.id for r in records]
    assert new.last_action.before == []
    assert new.focus_record_id == (records[0].id if count == 1 else None)
    assert new.pending is None and new.missing == []


@pytest.mark.parametrize("kind", ["update_record", "set_status"])
def test_agent07_before_is_deep_copied_and_nonmutations_preserve_last_action(state, kind):
    item = record(state)
    action = UpdateRecord(target=TargetRef(focus=True), title="Новое") if kind == "update_record" \
        else SetStatus(target=TargetRef(focus=True), status="done")
    before = [{"id": str(item.id), "title": "Старое", "nested": ["value"]}]
    new = update_state(state, action, ActionResult(action=kind, ok=True, records=[item]),
                       before=before)
    assert new.focus_record_id == item.id
    assert new.last_action.action == kind and new.last_action.before == before
    before[0]["nested"].clear()
    assert new.last_action.before[0]["nested"] == ["value"]
    for other in [Help(kind="help"), SearchRecords(query="текст"), ListRecords(date_from=NOW)]:
        newer = update_state(new, other, ActionResult(action=other.action, ok=True))
        assert newer.last_action == new.last_action
    assert state.last_action is None


def test_error_preserves_focus_and_last_action(state):
    item = record(state)
    state.focus_record_id = item.id
    state.last_action = LastAction(action="create_record", record_ids=[item.id])
    action = UpdateRecord(target=TargetRef(focus=True), title="Новое")
    new = update_state(state, action, ActionResult(action=action.action, ok=False, error="ошибка"))
    assert new == state


def test_candidates_are_not_grouped_and_successful_choice_replaces_shown(state):
    candidates = [record(state, start=NOW + timedelta(days=i)) for i in range(2)]
    action = SetStatus(target=TargetRef(text="Договор"), status="cancelled")
    waiting = update_state(state, action, ActionResult(
        action=action.action, ok=False, candidates=candidates,
    ))
    assert waiting.shown == waiting.candidates == [r.id for r in candidates]
    assert waiting.awaiting == "choice" and waiting.focus_record_id is None
    choice = action.model_copy(update={"target": TargetRef(index=2)})
    complete = update_state(waiting, choice, ActionResult(
        action=choice.action, ok=True, records=[candidates[1]],
    ), before=[candidates[1].model_dump(mode="json")])
    assert complete.shown == [candidates[1].id]
    assert complete.focus_record_id == candidates[1].id
    assert complete.pending is None and complete.awaiting is None and complete.candidates == []


def test_undo_and_restore_before_ambiguous_replacement_clear_last_action(state):
    item = record(state)
    state.last_action = LastAction(action="create_record", record_ids=[item.id])
    undone = update_state(state, UndoLast(), ActionResult(
        action="undo_last", ok=True, restored=[item],
    ))
    assert undone.last_action is None and undone.focus_record_id == item.id
    action = UpdateRecord(target=TargetRef(text="договор"), replaces_last=True)
    waiting = update_state(state, action, ActionResult(
        action=action.action, ok=False, restored=[item], candidates=[record(state), record(state)],
    ))
    assert waiting.last_action is None and waiting.awaiting == "choice"


@pytest.mark.parametrize("kind", ["list_records", "search_records"])
def test_group_order_matches_state_reply_and_context(state, kind):
    first = record(state, "Созвон", start=NOW)
    latest = record(state, "Созвон", start=NOW + timedelta(days=4))
    other = record(state, "Отчёт", deadline=NOW + timedelta(days=1))
    records = [first, other, latest]
    action = ListRecords(date_from=NOW) if kind == "list_records" else SearchRecords(query="всё")
    new = update_state(state, action, ActionResult(action=kind, ok=True, records=records))
    # Номера на экране — все записи в порядке ответа, без группировки (api.md, data-model.md)
    assert new.shown == [first.id, other.id, latest.id] and new.focus_record_id is None
    reply = reply_for_list(records, action, "UTC", NOW) if kind == "list_records" \
        else reply_for_search(records, "всё", "UTC", NOW)
    # Номеров в тексте нет: они на экране. Список называет записи по времени без свёртки,
    # поиск — одну ближайшую (assistant-texts 8, 9).
    assert "1)" not in reply
    if kind == "list_records":
        assert reply.casefold().index("созвон") < reply.casefold().index("отчёт")
    else:
        assert reply.startswith("Нашёл 3 задачи. Ближайшая")
    context = build_state_context(new, {r.id: r for r in records}, "UTC")
    assert context.index('1) task "Созвон"') < context.index('2) task "Отчёт"') \
        < context.index('3) task "Созвон"')
    assert "05.01.2030" in context
    assert len(records) == 3  # группировка не меняет выдачу сервисов


def test_grouping_does_not_merge_types_and_shown_keeps_all_numbers(state):
    active = record(state)
    done = active.model_copy(update={"id": uuid4(), "status": "done"})
    meeting = active.model_copy(update={"id": uuid4(), "type": "meeting", "start": NOW})
    assert len(group_records([active, done, meeting])) == 3
    action = SearchRecords(query="всё")
    items = [record(state, f"Дело {i}") for i in range(12)]
    new = update_state(state, action, ActionResult(action=action.action, ok=True, records=items))
    # Номер N — shown[N-1] и дальше десятого; в промпт попадают первые 10
    assert new.shown == [r.id for r in items]


def test_repeated_titles_are_several_records_and_give_no_focus(state):
    items = [record(state, start=NOW + timedelta(days=i)) for i in [2, 1, 3]]
    action = SearchRecords(query="договор")
    new = update_state(state, action, ActionResult(action=action.action, ok=True, records=items))
    assert new.shown == [r.id for r in items]
    assert new.focus_record_id is None


def test_missing_stores_action_and_empty_results_clear_focus(state):
    action = CreateRecord(type="meeting", title="Команда", time_given=False)
    waiting = update_state(state, action, ActionResult(
        action=action.action, ok=False, missing=["start"],
    ))
    assert waiting.pending.root == action and waiting.missing == ["start"]
    assert waiting.awaiting == "answer"
    waiting.focus_record_id = uuid4()
    action = SearchRecords(query="нет")
    empty = update_state(waiting, action, ActionResult(action=action.action, ok=True))
    assert empty.focus_record_id is None and empty.shown == [] and empty.pending_skipped


# --- AskUser.draft: уточнение при создании не теряет уже названное (кейсы 3.5, 3.8) ---

def _ask_with_draft(**draft):
    from schemas import AskDraft

    return AskUser(question="?", missing=draft.pop("missing"), draft=AskDraft(**draft))


def test_ask_with_draft_is_kept_as_pending_and_merged_on_repeat():
    from agent.state import pending_draft

    state = ConversationState(conversation_id=uuid4(), user_id=uuid4())
    first = _ask_with_draft(type="meeting", title="встреча с Сергеем", time="14:45",
                            missing=["start"])
    state = update_state(state, first, None)
    assert pending_draft(state).draft.time == "14:45"
    assert state.missing == ["start"] and state.awaiting == "answer"

    again = _ask_with_draft(title="встреча с Сергеем Петровым", missing=["start"])
    state = update_state(state, again, None)
    draft = pending_draft(state).draft
    assert (draft.type, draft.title, draft.time) == ("meeting", "встреча с Сергеем Петровым",
                                                     "14:45")


def test_ask_without_draft_keeps_old_behaviour():
    from agent.state import pending_draft

    state = ConversationState(conversation_id=uuid4(), user_id=uuid4())
    state = update_state(state, AskUser(question="?", missing=["start"]), None)
    assert state.pending is None and pending_draft(state) is None
    assert state.missing == ["start"] and state.awaiting == "answer"


def test_draft_type_and_time_win_answer_gives_title():
    """3.5: «Напомни завтра в 10» → «Позвонить маме»."""
    from agent.state import complete_from_draft, continues_pending

    tz = ZoneInfo("Europe/Moscow")
    ask = _ask_with_draft(type="reminder", start=datetime(2026, 10, 22, 10, tzinfo=tz),
                          time_given=True, missing=["title"])
    state = update_state(ConversationState(conversation_id=uuid4(), user_id=uuid4()), ask, None)
    answer = CreateRecord(type="task", title="позвонить маме", time_given=False)
    assert continues_pending(state, answer)
    action = complete_from_draft(ask, answer, "Europe/Moscow")
    assert action.type == "reminder"
    assert action.title == "позвонить маме"
    assert action.start == datetime(2026, 10, 22, 10, tzinfo=tz)
    assert action.time_given is True


def test_draft_time_goes_onto_answered_day():
    """3.8: «Встреча с Сергеем в 14:45» → «Завтра»."""
    from agent.state import complete_from_draft

    tz = ZoneInfo("Europe/Moscow")
    ask = _ask_with_draft(type="meeting", title="встреча с Сергеем", time="14:45",
                          missing=["start"])
    # День ответа пришёл в UTC: время ставится на день в поясе пользователя.
    answer = CreateRecord(type="meeting", title="встреча",
                          start=datetime(2026, 10, 21, 21, tzinfo=ZoneInfo("UTC")),
                          time_given=False)
    action = complete_from_draft(ask, answer, "Europe/Moscow")
    assert action.title == "встреча с Сергеем"
    assert action.start == datetime(2026, 10, 22, 14, 45, tzinfo=tz)
    assert action.time_given is True


def test_named_time_in_answer_is_not_overwritten_by_draft_time():
    from agent.state import complete_from_draft

    tz = ZoneInfo("Europe/Moscow")
    ask = _ask_with_draft(type="meeting", title="встреча с Сергеем", time="14:45",
                          missing=["start"])
    answer = CreateRecord(type="meeting", title="встреча с Сергеем",
                          start=datetime(2026, 10, 22, 16, tzinfo=tz), time_given=True)
    assert complete_from_draft(ask, answer, "Europe/Moscow").start.hour == 16
