import asyncio
from datetime import UTC, datetime
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import openai
import pytest

from agent import actions as actions_module
from agent import agent as agent_module
from agent.agent import ActionParseError, process_user_turn
from schemas import ActionResult, AskUser, ConversationState, CreateRecord, Help, SearchRecords
from services.records import validate_create


@pytest.fixture(autouse=True)
def conversation_store(monkeypatch):
    """Тесты агента без сети/БД; состояние проходит реальную JSON-валидацию."""
    states = {}
    main_thread = get_ident()

    def load(db, cid, uid):
        assert get_ident() != main_thread
        if cid not in states:
            states[cid] = ConversationState(conversation_id=cid, user_id=uid)
        assert states[cid].user_id == uid
        return states[cid].model_copy(deep=True)

    def save(db, state):
        assert get_ident() != main_thread
        states[state.conversation_id] = ConversationState.model_validate_json(
            state.model_dump_json()
        )

    monkeypatch.setattr(agent_module, "get_or_create_conversation_state", load)
    monkeypatch.setattr(agent_module, "save_conversation_state", save)
    monkeypatch.setattr(agent_module, "get_record", lambda *args: None)
    monkeypatch.setattr(actions_module, "search_by_substring", lambda *args: [])
    return states


def turn(text="привет"):
    cid = uuid4()
    response = asyncio.run(process_user_turn(None, uuid4(), cid, text, "Europe/Moscow"))
    return cid, response


def test_llm_timeout_gives_polite_reply(monkeypatch):
    async def boom(*args, **kwargs):
        raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com"))

    monkeypatch.setattr(agent_module, "get_action", boom)
    cid, r = turn()
    assert "временно недоступен" in r.reply
    assert r.conversation_id == cid
    assert r.result is None


def test_unparseable_action_gives_polite_reply(monkeypatch):
    async def bad(*args, **kwargs):
        raise ActionParseError("мусор")

    monkeypatch.setattr(agent_module, "get_action", bad)
    _, r = turn()
    assert "Не удалось разобрать" in r.reply


def test_meeting_without_time_asks_question(monkeypatch):
    async def meeting(*args, **kwargs):
        return CreateRecord(type="meeting", title="встреча с Иваном", time_given=False)

    monkeypatch.setattr(agent_module, "get_action", meeting)
    _, r = turn("поставь встречу с Иваном завтра")
    assert r.awaiting == "answer"
    assert "время" in r.reply


def test_missing_llm_config_gives_polite_reply(monkeypatch):
    # Настоящий get_action и make_client: ключа и модели нет ни в LLMConfig, ни в окружении.
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    cid, r = turn()
    assert "не настроен" in r.reply
    assert r.conversation_id == cid
    assert r.result is None


def test_missing_model_gives_polite_reply(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    _, r = turn()
    assert "не настроен" in r.reply


@pytest.mark.parametrize("date_only_step", [False, True])
def test_slot_filling_preserves_draft_and_clears_only_after_success(
    monkeypatch, conversation_store, date_only_step,
):
    from schemas import Record

    cid, uid, rid = uuid4(), uuid4(), uuid4()
    contexts, created = [], []
    start = datetime(2030, 1, 10, 15, tzinfo=UTC)
    end = start.replace(hour=16)
    responses = [CreateRecord(
        type="meeting", title="встреча с Денисом", end=end, time_given=False,
    )]
    if date_only_step:
        responses.append(CreateRecord(
            type="meeting", title="не заменять название", start=start.replace(hour=0),
            time_given=False,
        ))
    responses.append(CreateRecord(
        type="meeting", title="не заменять название", start=start, time_given=True,
    ))
    actions = iter(responses)

    async def get_action(*args, context="", **kwargs):
        contexts.append(context)
        return next(actions)

    main_thread = get_ident()

    def create(db, user_id, action):
        assert get_ident() != main_thread
        # Реальные бизнес-правила: полночь без time_given не завершает встречу.
        error = validate_create(action, datetime(2030, 1, 1, tzinfo=UTC))
        if error is not None:
            return error
        created.append(action)
        record = Record(
            id=rid, user_id=user_id, type=action.type, title=action.title,
            start=action.start, end=action.end, created_at=datetime(2030, 1, 1, tzinfo=UTC),
        )
        return ActionResult(action=action.action, ok=True, records=[record])

    monkeypatch.setattr(agent_module, "get_action", get_action)
    monkeypatch.setattr(actions_module, "create_record", create)

    def send(text):
        return asyncio.run(process_user_turn(None, uid, cid, text, "UTC"))

    first = send("Поставь встречу с Денисом")
    assert first.awaiting == "answer"
    assert first.result.missing == ["start"]
    assert created == []
    assert conversation_store[cid].pending.root.title == "встреча с Денисом"
    if date_only_step:
        assert send("10 января").awaiting == "answer"
        assert conversation_store[cid].missing == ["start"]
        assert conversation_store[cid].pending.root.start == start.replace(hour=0)
        assert created == []
    last = send("В 15:00")
    assert last.awaiting is None
    assert last.result.ok
    assert len(created) == 1
    assert created[0].title == "встреча с Денисом"
    assert created[0].start == start
    assert created[0].end == end
    assert contexts[0] == ""
    assert "встреча с Денисом" in contexts[1]
    assert "Поставь" not in contexts[1]
    state = conversation_store[cid]
    assert state.focus_record_id == rid
    assert state.pending is None
    assert state.missing == state.candidates == []
    assert state.awaiting is None


@pytest.mark.parametrize("next_step", ["ask", "timeout", "parse", "service_error", "search"])
def test_unfinished_draft_survives_questions_errors_and_independent_search(
    monkeypatch, conversation_store, next_step,
):
    from schemas import LLMAction

    cid, uid = uuid4(), uuid4()
    draft = CreateRecord(type="meeting", title="встреча с Денисом", time_given=False)
    conversation_store[cid] = ConversationState(
        conversation_id=cid, user_id=uid, pending=LLMAction(draft),
        missing=["start"], awaiting="answer",
    )

    async def get_action(*args, **kwargs):
        if next_step == "timeout":
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com"))
        if next_step == "parse":
            raise ActionParseError("bad")
        if next_step == "ask":
            return AskUser(question="Уточните время", missing=["start"])
        if next_step == "search":
            return SearchRecords(query="договор")
        return draft.model_copy(update={
            "start": datetime(2000, 1, 1, tzinfo=UTC), "time_given": True,
        })

    monkeypatch.setattr(agent_module, "get_action", get_action)
    response = asyncio.run(process_user_turn(None, uid, cid, "ответ", "UTC"))
    assert response.awaiting == "answer"
    state = conversation_store[cid]
    assert state.pending.root.title == draft.title
    assert state.missing == ["start"]
    assert state.awaiting == "answer"
    if next_step == "service_error":
        assert response.result.ok is False
        assert "прошлом" in response.reply


def test_get_action_sends_only_current_text_and_compact_context(monkeypatch):
    action = CreateRecord(type="meeting", title="встреча", time_given=False)
    call = SimpleNamespace(function=SimpleNamespace(
        name=action.action, arguments=action.model_dump_json(),
    ))
    create = AsyncMock(return_value=SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(tool_calls=[call])),
    ]))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(agent_module, "make_client", lambda _: (client, "test-model"))
    result = asyncio.run(agent_module.get_action(
        "В 15:00", datetime(2030, 1, 1, tzinfo=UTC), "UTC", context="[Черновик: тест]",
    ))
    assert result == action
    create.assert_awaited_once()
    messages = create.call_args.kwargs["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].endswith("\n[Черновик: тест]")
    assert messages[1] == {"role": "user", "content": "В 15:00"}


@pytest.mark.parametrize("exists", [False, True])
def test_focus_is_loaded_for_owner_or_cleared(monkeypatch, conversation_store, exists):
    from schemas import Record

    cid, uid, rid = uuid4(), uuid4(), uuid4()
    conversation_store[cid] = ConversationState(
        conversation_id=cid, user_id=uid, focus_record_id=rid,
    )
    record = Record(
        id=rid, user_id=uid, type="task", title="Договор",
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
    )

    def load(db, owner, record_id):
        assert (owner, record_id) == (uid, rid)
        return record if exists else None

    async def get_action(*args, context="", **kwargs):
        if exists:
            assert str(rid) not in context and "Договор" in context
        else:
            assert context == ""
        return AskUser(question="Уточните действие", missing=[])

    monkeypatch.setattr(agent_module, "get_record", load)
    monkeypatch.setattr(agent_module, "get_action", get_action)
    asyncio.run(process_user_turn(None, uid, cid, "покажи её", "UTC"))
    assert conversation_store[cid].focus_record_id == (rid if exists else None)


def test_new_conversation_does_not_receive_another_draft(monkeypatch, conversation_store):
    async def get_action(*args, context="", **kwargs):
        assert context == ""
        return CreateRecord(type="meeting", title="Встреча", time_given=False)

    monkeypatch.setattr(agent_module, "get_action", get_action)
    first, _ = turn("Встреча")
    second, _ = turn("Другая встреча")
    assert first != second
    assert len(conversation_store) == 2


def test_time_given_without_start_does_not_turn_draft_date_into_midnight(
    monkeypatch, conversation_store,
):
    from schemas import LLMAction

    cid, uid = uuid4(), uuid4()
    midnight = datetime(2030, 1, 10, tzinfo=UTC)
    conversation_store[cid] = ConversationState(
        conversation_id=cid, user_id=uid, awaiting="answer", missing=["start"],
        pending=LLMAction(CreateRecord(
            type="meeting", title="Встреча", start=midnight, time_given=False,
        )),
    )

    async def get_action(*args, **kwargs):
        return CreateRecord(type="meeting", title="Встреча", time_given=True)

    monkeypatch.setattr(agent_module, "get_action", get_action)
    result = asyncio.run(process_user_turn(None, uid, cid, "В 15:00", "UTC"))
    assert result.awaiting == "answer"
    assert result.result.missing == ["start"]
    assert conversation_store[cid].pending.root.start == midnight
    assert conversation_store[cid].pending.root.time_given is False


@pytest.mark.parametrize("kind", ["help", "offtopic"])
def test_help_does_not_list_or_create_records(monkeypatch, kind):
    async def get_action(*args, **kwargs):
        return Help(kind=kind)

    def unexpected(*args):
        raise AssertionError("справка не должна обращаться к записям")

    monkeypatch.setattr(agent_module, "get_action", get_action)
    monkeypatch.setattr(actions_module, "create_record", unexpected)
    monkeypatch.setattr(actions_module, "list_records_for_period", unexpected)
    monkeypatch.setattr(actions_module, "search_by_substring", unexpected)
    _, result = turn("Привет")
    assert result.result.action == "help"
    assert result.result.ok
    assert result.awaiting is None
    assert "задачами" in result.reply


@pytest.mark.parametrize("action_name", ["list_records", "search_records"])
@pytest.mark.parametrize("count", [0, 1, 2])
def test_list_search_preserve_draft_and_save_focus_once(
    monkeypatch, conversation_store, action_name, count,
):
    from schemas import ListRecords, LLMAction, Record, SearchHit

    cid, uid = uuid4(), uuid4()
    old = Record(id=uuid4(), user_id=uid, type="task", title="Старое", created_at=datetime.now(UTC))
    conversation_store[cid] = ConversationState(
        conversation_id=cid, user_id=uid, focus_record_id=old.id, awaiting="answer",
        missing=["start"], pending=LLMAction(CreateRecord(
            type="meeting", title="встреча с Денисом", time_given=False,
        )),
    )
    records = [old.model_copy(update={"id": uuid4(), "title": f"Дело {i}"}) for i in range(count)]
    action = SearchRecords(query="дело") if action_name == "search_records" else ListRecords(
        date_from=datetime(2030, 1, 1, tzinfo=UTC),
    )
    monkeypatch.setattr(agent_module, "get_action", AsyncMock(return_value=action))
    monkeypatch.setattr(agent_module, "get_record", lambda *args: old)
    monkeypatch.setattr(actions_module, "search_by_substring", lambda *args: [
        SearchHit(record=record, score=1.0) for record in records
    ])
    monkeypatch.setattr(actions_module, "list_records_for_period", lambda *args: ActionResult(
        action="list_records", ok=True, records=records,
    ))
    saved = []
    save = agent_module.save_conversation_state

    def save_once(db, state):
        saved.append(state)
        save(db, state)

    monkeypatch.setattr(agent_module, "save_conversation_state", save_once)
    result = asyncio.run(process_user_turn(None, uid, cid, "Покажи дела", "UTC"))
    assert len(saved) == 1
    state = conversation_store[cid]
    assert state.focus_record_id == (records[0].id if count == 1 else None)
    assert state.pending.root.title == "встреча с Денисом"
    assert state.missing == ["start"]
    assert result.awaiting == "answer"
    assert result.result.records == records
    if action_name == "search_records" and count == 0:
        assert "По запросу «дело»" in result.reply
    if action_name == "list_records":
        assert "Начиная с 1 января 2030 года" in result.reply


def test_creation_of_another_type_does_not_reuse_meeting_title(monkeypatch, conversation_store):
    from schemas import LLMAction, Record

    uid, cid = uuid4(), uuid4()
    conversation_store[cid] = ConversationState(
        conversation_id=cid, user_id=uid, awaiting="answer", missing=["start"],
        pending=LLMAction(CreateRecord(type="meeting", title="Встреча", time_given=False)),
    )
    action = CreateRecord(type="task", title="Купить хлеб", time_given=False)
    monkeypatch.setattr(agent_module, "get_action", AsyncMock(return_value=action))

    def create(db, owner, incoming):
        assert incoming == action
        return ActionResult(action="create_record", ok=True, records=[Record(
            id=uuid4(), user_id=owner, type=incoming.type, title=incoming.title,
            created_at=datetime.now(UTC),
        )])

    monkeypatch.setattr(actions_module, "create_record", create)
    response = asyncio.run(process_user_turn(None, uid, cid, "Купить хлеб", "UTC"))
    assert response.result.records[0].title == "Купить хлеб"
    assert response.awaiting is None
    assert conversation_store[cid].pending is None


@pytest.mark.parametrize("awaiting", ["answer", "choice"])
def test_refusal_clears_waiting_before_llm_or_record_reads(
    monkeypatch, conversation_store, awaiting,
):
    from schemas import LastAction, LLMAction

    uid, cid, rid = uuid4(), uuid4(), uuid4()
    state = ConversationState(
        conversation_id=cid, user_id=uid, awaiting=awaiting, missing=["start"],
        pending=LLMAction(CreateRecord(type="meeting", title="Команда", time_given=False)),
        pending_skipped=True, candidates=[rid], shown=[rid], focus_record_id=rid,
        last_action=LastAction(action="create_record", record_ids=[rid]),
    )
    conversation_store[cid] = state
    model = AsyncMock(side_effect=AssertionError("отказ не должен вызывать модель"))
    monkeypatch.setattr(agent_module, "get_action", model)
    monkeypatch.setattr(agent_module, "get_record", lambda *args: pytest.fail("лишнее чтение"))
    response = asyncio.run(process_user_turn(None, uid, cid, "  НЕ   НАДО!!! ", "UTC"))
    model.assert_not_awaited()
    assert response.awaiting is None and response.result is None
    assert response.reply == "Хорошо, не ставлю."
    saved = conversation_store[cid]
    assert saved.pending is None and not saved.pending_skipped
    assert saved.candidates == saved.missing == []
    assert saved.last_action == state.last_action and saved.focus_record_id == rid
    assert saved.shown == [rid]


def test_cancel_command_is_sent_to_model(monkeypatch, conversation_store):
    from schemas import LLMAction

    uid, cid = uuid4(), uuid4()
    conversation_store[cid] = ConversationState(
        conversation_id=cid, user_id=uid, awaiting="answer", missing=["start"],
        pending=LLMAction(CreateRecord(type="meeting", title="Команда", time_given=False)),
    )
    model = AsyncMock(return_value=AskUser(question="Какую встречу?", missing=[]))
    monkeypatch.setattr(agent_module, "get_action", model)
    response = asyncio.run(process_user_turn(None, uid, cid, "Отмени встречу с Иваном", "UTC"))
    model.assert_awaited_once()
    assert response.reply == "Какую встречу?"
    assert conversation_store[cid].pending is not None


@pytest.mark.parametrize("second_detour", [False, True])
def test_interrupted_creation_resumes_once_then_expires(
    monkeypatch, conversation_store, second_detour,
):
    from schemas import ListRecords, Record

    uid, cid = uuid4(), uuid4()
    start = datetime(2035, 1, 10, 16, tzinfo=UTC)
    meeting = CreateRecord(type="meeting", title="Встреча с Иваном",
                           start=start.replace(hour=0), time_given=False)
    actions = [meeting, ListRecords(date_from=start.replace(hour=0))]
    if second_detour:
        actions.extend([
            Help(kind="offtopic"), AskUser(question="Что поставить в 16?", missing=["title"]),
        ])
    else:
        actions.append(meeting.model_copy(update={"title": "не заменять", "start": start,
                                                 "time_given": True}))
    incoming, contexts = iter(actions), []

    async def get_action(*args, context="", **kwargs):
        contexts.append(context)
        return next(incoming)

    def create(db, owner, action):
        error = validate_create(action, datetime(2030, 1, 1, tzinfo=UTC))
        if error:
            return error
        return ActionResult(action=action.action, ok=True, records=[Record(
            id=uuid4(), user_id=owner, type=action.type, title=action.title,
            start=action.start, created_at=datetime(2030, 1, 1, tzinfo=UTC),
        )])

    monkeypatch.setattr(agent_module, "get_action", get_action)
    monkeypatch.setattr(actions_module, "create_record", create)
    monkeypatch.setattr(actions_module, "list_records_for_period", lambda *args: ActionResult(
        action="list_records", ok=True,
    ))

    def send(text):
        return asyncio.run(process_user_turn(None, uid, cid, text, "UTC"))

    assert send("Поставь встречу с Иваном завтра").awaiting == "answer"
    detour = send("А что у меня завтра?")
    assert "ещё не создана" in detour.reply and "Встреча с Иваном" in detour.reply
    assert conversation_store[cid].pending_skipped
    if second_detour:
        second = send("Какая погода?")
        assert second.awaiting is None and "ещё не создана" not in second.reply
        assert conversation_store[cid].pending is None
    final = send("В 16")
    if second_detour:
        assert "Черновик" not in contexts[-1]
        assert final.result is None and final.reply == "Что поставить в 16?"
    else:
        assert "Черновик" in contexts[-1]
        assert final.result.ok and final.awaiting is None
        assert final.result.records[0].start == start
        assert final.result.records[0].title == meeting.title
        saved = conversation_store[cid]
        assert saved.last_action.record_ids == [final.result.records[0].id]
        assert saved.pending is None and not saved.pending_skipped


def test_loads_owned_shown_focus_last_action_once_and_keeps_number_gaps(
    monkeypatch, conversation_store,
):
    from schemas import LastAction, Record

    uid, cid, deleted = uuid4(), uuid4(), uuid4()
    item = Record(id=uuid4(), user_id=uid, type="task", title="Договор",
                  created_at=datetime(2030, 1, 1, tzinfo=UTC))
    conversation_store[cid] = ConversationState(
        conversation_id=cid, user_id=uid, shown=[deleted, item.id], focus_record_id=item.id,
        last_action=LastAction(action="create_record", record_ids=[item.id]),
    )
    reads = []

    def load(db, owner, rid):
        assert owner == uid
        reads.append(rid)
        return item if rid == item.id else None

    async def get_action(*args, context="", **kwargs):
        assert "2) task" in context and "1)" not in context
        assert "В фокусе" in context and "Последнее действие" in context
        assert str(item.id) not in context
        return Help(kind="help")

    monkeypatch.setattr(agent_module, "get_record", load)
    monkeypatch.setattr(agent_module, "get_action", get_action)
    asyncio.run(process_user_turn(None, uid, cid, "Что ты умеешь?", "UTC"))
    assert reads == [deleted, item.id]


def test_state_save_failure_propagates_instead_of_confirming(monkeypatch):
    monkeypatch.setattr(agent_module, "get_action", AsyncMock(return_value=Help(kind="help")))

    def broken(*args):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(agent_module, "save_conversation_state", broken)
    with pytest.raises(RuntimeError, match="storage unavailable"):
        turn()
