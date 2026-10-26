import json
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent.context import build_draft_context, build_focus_context
from schemas import ConversationState, CreateRecord, LLMAction, Record


def test_draft_context_is_one_line_of_state_without_history():
    state = ConversationState(
        conversation_id=uuid4(), user_id=uuid4(),
        pending=LLMAction(CreateRecord(
            type="meeting", title='встреча с "Денисом"\nобсуждение',
            start=datetime(2030, 1, 10, tzinfo=ZoneInfo("Europe/Moscow")), time_given=False,
        )),
        missing=["start"], awaiting="answer",
    )
    context = build_draft_context(state)
    assert len(context.splitlines()) == 1
    data = json.loads(context.removeprefix("[Черновик: ").removesuffix("]"))
    assert data == {
        "pending": state.pending.model_dump(mode="json"),
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
