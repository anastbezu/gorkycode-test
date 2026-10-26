"""Схемы бонусных действий и новые поля состояния — по docs/contracts/."""

from uuid import uuid4

from schemas import (
    ConversationState,
    Help,
    LastAction,
    ListRecords,
    LLMAction,
    SetStatus,
    UndoLast,
    UpdateRecord,
)


def test_bonus_actions_parse_by_discriminator():
    update = LLMAction.model_validate(
        {
            "action": "update_record",
            "target": {"index": 2},
            "start": "2026-10-23T15:00:00+03:00",
        }
    ).root
    assert isinstance(update, UpdateRecord)
    assert update.target.index == 2
    assert update.replaces_last is False

    status = LLMAction.model_validate(
        {"action": "set_status", "target": {"focus": True}, "status": "cancelled"}
    ).root
    assert isinstance(status, SetStatus)
    assert status.target.focus is True

    assert isinstance(LLMAction.model_validate({"action": "undo_last"}).root, UndoLast)
    assert isinstance(LLMAction.model_validate({"action": "help", "kind": "offtopic"}).root, Help)


def test_list_records_without_end():
    action = ListRecords.model_validate({"date_from": "2026-10-21T00:00:00+03:00"})
    assert action.date_to is None


def test_conversation_state_new_fields_default_empty():
    state = ConversationState(conversation_id=uuid4(), user_id=uuid4())
    assert state.shown == []
    assert state.last_action is None
    assert state.pending_skipped is False

    record_id = uuid4()
    state.last_action = LastAction(
        action="update_record", record_ids=[record_id], before=[{"start": None}]
    )
    restored = ConversationState.model_validate(state.model_dump(mode="json"))
    assert restored.last_action.record_ids == [record_id]
