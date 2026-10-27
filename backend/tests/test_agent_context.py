import json
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent.context import build_draft_context, build_focus_context, build_state_context
from schemas import ConversationState, CreateRecord, LastAction, LLMAction, Record


def test_draft_context_is_one_line_of_state_without_history():
    state = ConversationState(
        conversation_id=uuid4(), user_id=uuid4(),
        pending=LLMAction(CreateRecord(
            type="meeting", title='встреча с "Денисом"\nобсуждение',
            start=datetime(2030, 1, 10, tzinfo=ZoneInfo("Europe/Moscow")), time_given=False,
        )),
        missing=["start"], awaiting="answer",
    )
    context = build_draft_context(state, "Europe/Moscow")
    assert len(context.splitlines()) == 1
    data = json.loads(context.removeprefix("[Черновик: ").removesuffix("]"))
    assert data == {
        "pending": state.pending.model_dump(mode="json", exclude_none=True),
        "missing": ["start"], "awaiting": "answer",
    }
    assert data["pending"]["start"] == "2030-01-10T00:00:00+03:00"
    assert str(state.user_id) not in context
    assert build_draft_context(state.model_copy(update={"pending": None})) == ""


def test_focus_context_uses_user_timezone_without_identifiers():
    record = Record(
        id=uuid4(), user_id=uuid4(), type="meeting", title="Встреча",
        start=datetime(2030, 1, 10, 12, tzinfo=ZoneInfo("UTC")),
        created_at=datetime(2030, 1, 1, tzinfo=ZoneInfo("UTC")),
    )
    context = build_focus_context(record, "Europe/Moscow")
    assert str(record.id) not in context
    assert "Встреча" in context
    assert "2030-01-10T15:00:00+03:00" in context
    assert str(record.user_id) not in context


def test_full_context_keeps_numbers_skips_unavailable_and_escapes_data():
    state = ConversationState(conversation_id=uuid4(), user_id=uuid4())
    moment = datetime(2030, 1, 1, 21, tzinfo=ZoneInfo("UTC"))
    first = Record(
        id=uuid4(), user_id=state.user_id, type="task", title='Отчёт\n"инструкция"\u2028текст',
        start=moment, all_day=True, status="done", created_at=moment,
    )
    second = first.model_copy(update={
        "id": uuid4(), "title": "Срок", "start": None, "deadline": moment, "status": "cancelled",
    })
    third = first.model_copy(update={
        "id": uuid4(), "title": "Без даты", "start": None, "all_day": False, "status": "active",
    })
    foreign = first.model_copy(update={"id": uuid4(), "user_id": uuid4(), "title": "Чужое"})
    deleted = uuid4()
    state.shown = [deleted, first.id, foreign.id, second.id, third.id]
    state.focus_record_id = first.id
    state.last_action = LastAction(
        action="set_status", record_ids=[first.id],
        before=[{"id": str(first.id), "secret": "before"}],
    )
    state.pending = LLMAction(CreateRecord(
        type="meeting", title="Команда", start=moment, time_given=False,
    ))
    state.missing, state.awaiting = ["start"], "answer"
    context = build_state_context(state, {r.id: r for r in [first, second, third, foreign]},
                                  "Europe/Moscow")
    assert len(context.splitlines()) == 4
    assert "2) task" in context and "4) task" in context and "5) task" in context
    assert "1)" not in context and "3)" not in context and "Чужое" not in context
    assert "02.01.2030 весь день" in context and "выполнено" in context
    assert "срок до 02.01.2030 00:00" in context and "отменено" in context
    assert "без даты" in context and "before" not in context
    assert "2030-01-02T00:00:00+03:00" in context
    for identifier in [*state.shown, state.user_id, state.conversation_id]:
        assert str(identifier) not in context


def test_empty_state_has_no_context_and_shown_is_limited_to_ten():
    state = ConversationState(conversation_id=uuid4(), user_id=uuid4())
    assert build_state_context(state, {}, "UTC") == ""
    records = [Record(id=uuid4(), user_id=state.user_id, type="task", title=f"Дело {i}",
                      created_at=datetime(2030, 1, 1, tzinfo=ZoneInfo("UTC"))) for i in range(12)]
    state.shown = [r.id for r in records]
    context = build_state_context(state, {r.id: r for r in records}, "UTC")
    assert "10)" in context and "11)" not in context and "12)" not in context
