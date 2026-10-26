import asyncio
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent import agent as agent_module
from agent.agent import process_user_turn
from db import models
from schemas import CreateRecord, RecordType

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 21, 10, 0, tzinfo=MSK)  # среда, как в test-cases.md


def _turn(db: Session, monkeypatch, action: CreateRecord, text: str):
    monkeypatch.setattr(agent_module, "get_action", AsyncMock(return_value=action))
    user_id = uuid4()
    response = asyncio.run(
        process_user_turn(db, user_id, uuid4(), text, "Europe/Moscow", now=NOW)
    )
    rows = db.scalars(select(models.Record).where(models.Record.user_id == user_id)).all()
    return response, rows


def test_meeting_with_time_is_saved(db: Session, monkeypatch) -> None:
    start = datetime(2026, 10, 22, 15, 0, tzinfo=MSK)
    action = CreateRecord(
        type=RecordType.MEETING, title="встреча с Иваном", start=start, time_given=True
    )

    response, rows = _turn(db, monkeypatch, action, "Поставь встречу с Иваном завтра в 15:00")

    assert response.result.ok
    assert len(rows) == 1
    assert rows[0].type is RecordType.MEETING
    assert rows[0].start == start
    assert "15:00" in response.reply


def test_task_without_time_is_all_day(db: Session, monkeypatch) -> None:
    day = datetime(2026, 10, 22, 0, 0, tzinfo=MSK)
    action = CreateRecord(type=RecordType.TASK, title="купить хлеб", start=day, time_given=False)

    response, rows = _turn(db, monkeypatch, action, "Купить хлеб завтра")

    assert response.result.ok
    assert rows[0].all_day is True
    assert "00:00" not in response.reply


def test_date_in_past_is_polite_error(db: Session, monkeypatch) -> None:
    past = datetime(2026, 10, 20, 10, 0, tzinfo=MSK)
    action = CreateRecord(
        type=RecordType.REMINDER, title="позвонить Ивану", start=past, time_given=True
    )

    response, rows = _turn(db, monkeypatch, action, "Напомни вчера позвонить Ивану")

    assert response.result.ok is False
    assert "прошлом" in response.reply
    assert rows == []