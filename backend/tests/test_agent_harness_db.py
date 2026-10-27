"""Быстрый слой автотеста на тестовой PostgreSQL (agent-08): модель — сценарий, всё
остальное настоящее — `process_user_turn`, сервисы записей и состояние разговора.
Без базы тесты пропускаются, в CI выполняются."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import models
from schemas import CreateRecord
from services import get_conversation_state
from tests.agent_cases import CASES
from tests.agent_compare import compare
from tests.agent_live import TZ, Harness


def scripted(*actions):
    queue = list(actions)

    async def model(*args, **kwargs):
        return queue.pop(0)

    return model


def expect(case_id: str, turn: int = 0):
    return next(c for c in CASES if c.id == case_id).turns[turn].expect


def records(db: Session, user_id):
    return db.scalars(select(models.Record).where(models.Record.user_id == user_id)).all()


def test_dialog_saves_draft_then_creates_record(db: Session, monkeypatch) -> None:
    first = CreateRecord(type="meeting", title="встреча с Иваном",
                         start=datetime(2026, 10, 22, tzinfo=TZ), time_given=False)
    # Чужое название во второй реплике: верное есть только в сохранённом черновике.
    second = CreateRecord(type="meeting", title="не то название",
                          start=datetime(2026, 10, 22, 15, tzinfo=TZ), time_given=True)
    harness = Harness(monkeypatch, scripted(first, second), db=db)
    user_id, conversation_id = uuid4(), uuid4()

    observed, _ = harness.run_turn("Поставь встречу с Иваном завтра", user_id, conversation_id)
    assert compare(expect("1.15", 0), observed, TZ) == []
    state = get_conversation_state(db, conversation_id, user_id)
    assert state.pending is not None
    assert state.pending.root.title == "встреча с Иваном"
    assert state.missing == ["start"]
    assert records(db, user_id) == []

    observed, _ = harness.run_turn("в 15:00", user_id, conversation_id)
    assert compare(expect("1.15", 1), observed, TZ) == []
    [row] = records(db, user_id)
    assert row.title == "встреча с Иваном"
    assert row.start == datetime(2026, 10, 22, 15, tzinfo=TZ)
    assert row.all_day is False
    state = get_conversation_state(db, conversation_id, user_id)
    assert state.pending is None
    assert state.focus_record_id == row.id


def test_single_creation_is_saved_with_time(db: Session, monkeypatch) -> None:
    action = CreateRecord(type="reminder", title="позвонить Ивану",
                          start=datetime(2026, 10, 22, 10, tzinfo=TZ), time_given=True)
    harness = Harness(monkeypatch, scripted(action), db=db)
    user_id = uuid4()

    observed, _ = harness.run_turn("Напомни мне завтра в 10 утра позвонить Ивану",
                                   user_id, uuid4())
    assert compare(expect("1.1"), observed, TZ) == []
    [row] = records(db, user_id)
    assert row.start == datetime(2026, 10, 22, 10, tzinfo=TZ)
    assert row.all_day is False


def test_date_in_past_creates_nothing(db: Session, monkeypatch) -> None:
    action = CreateRecord(type="reminder", title="позвонить Ивану",
                          start=datetime(2026, 10, 20, tzinfo=TZ), time_given=False)
    harness = Harness(monkeypatch, scripted(action), db=db)
    user_id = uuid4()

    observed, _ = harness.run_turn("Напомни вчера позвонить Ивану", user_id, uuid4())
    assert compare(expect("8.3"), observed, TZ) == []
    assert records(db, user_id) == []
