import asyncio
import logging
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from agent import focus
from schemas import ActionResult, Record

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))


class FakeDb:
    def __init__(self):
        self.rolled_back = False

    def rollback(self):
        self.rolled_back = True


def test_db_error_is_rolled_back_and_logged(monkeypatch, caplog):
    def broken(*args):
        raise SQLAlchemyError("connection lost")

    monkeypatch.setattr(focus, "get_or_create_conversation_state", broken)
    db = FakeDb()

    with caplog.at_level(logging.ERROR, logger="agent.focus"):
        focus._save_focus(db, uuid4(), uuid4(), uuid4())

    assert db.rolled_back
    assert "не удалось сохранить фокус" in caplog.text


def test_foreign_conversation_is_logged(monkeypatch, caplog):
    def foreign(*args):
        raise focus.ConversationAccessError("чужой")

    monkeypatch.setattr(focus, "_save_focus", foreign)
    record = Record(id=uuid4(), user_id=uuid4(), type="task", title="Договор", created_at=NOW)
    result = ActionResult(action="search_records", ok=True, records=[record])

    with caplog.at_level(logging.WARNING, logger="agent.focus"):
        asyncio.run(focus.remember_focus("db", uuid4(), uuid4(), result))

    assert "фокус не сохранён" in caplog.text