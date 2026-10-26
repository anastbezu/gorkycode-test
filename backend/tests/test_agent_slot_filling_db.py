"""Сценарий уточнения на реальных сервисах PostgreSQL; LLM подменена, сети LLM нет."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from agent import agent as agent_module
from schemas import CreateRecord, ListRecords
from services.conversation import ConversationAccessError, get_or_create_conversation_state
from services.records import create_record, get_record, list_records_for_period


def test_two_turns_persist_record_clear_draft_and_isolate_owner(db, monkeypatch):
    uid, cid = uuid4(), uuid4()
    start = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=0)
    actions = iter([
        CreateRecord(type="meeting", title="встреча с Денисом", time_given=False),
        CreateRecord(
            type="meeting", title="встреча с Денисом", start=start, time_given=True,
        ),
    ])
    monkeypatch.setattr(agent_module, "get_action", _action_source(actions))

    first = asyncio.run(agent_module.process_user_turn(db, uid, cid, "Встреча", "UTC"))
    assert first.awaiting == "answer"
    db.expire_all()
    state = get_or_create_conversation_state(db, cid, uid)
    assert state.pending.root.title == "встреча с Денисом"
    assert state.missing == ["start"]

    last = asyncio.run(agent_module.process_user_turn(db, uid, cid, "В 15:00", "UTC"))
    assert last.result.ok
    assert last.awaiting is None
    db.expire_all()
    state = get_or_create_conversation_state(db, cid, uid)
    assert state.pending is None
    assert state.missing == state.candidates == []
    assert state.focus_record_id == last.result.records[0].id
    record = get_record(db, uid, state.focus_record_id)
    assert record.title == "встреча с Денисом"
    assert record.start == start
    assert get_record(db, uuid4(), record.id) is None
    assert get_record(db, uid, uuid4()) is None
    with pytest.raises(ConversationAccessError):
        get_or_create_conversation_state(db, cid, uuid4())


def _action_source(actions):
    async def get_action(*args, **kwargs):
        return next(actions)
    return get_action


def test_open_ended_list_includes_future_and_undated_records(db):
    uid = uuid4()
    now = datetime.now(UTC)
    dated = create_record(db, uid, CreateRecord(
        type="task", title="Завтра", start=now + timedelta(days=1), time_given=True,
    )).records[0]
    undated = create_record(db, uid, CreateRecord(
        type="task", title="Без срока", time_given=False,
    )).records[0]
    create_record(db, uuid4(), CreateRecord(type="task", title="Чужое", time_given=False))
    result = list_records_for_period(db, uid, ListRecords(date_from=now))
    assert [record.id for record in result.records] == [dated.id, undated.id]
