import asyncio
import threading
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent import focus
from agent.focus import focus_record_id, remember_focus
from schemas import ActionResult, Record

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))


def make(title):
    return Record(id=uuid4(), user_id=uuid4(), type="task", title=title, created_at=NOW)


def test_single_search_hit_becomes_focus():
    record = make("Подписать договор")
    result = ActionResult(action="search_records", ok=True, records=[record])
    assert focus_record_id(result) == record.id


def test_several_hits_give_no_focus():
    records = [make("Договор 1"), make("Договор 2")]
    result = ActionResult(action="search_records", ok=True, records=records)
    assert focus_record_id(result) is None


def test_nothing_found_gives_no_focus():
    result = ActionResult(action="search_records", ok=True, records=[])
    assert focus_record_id(result) is None


def test_list_with_one_record_gives_no_focus():
    result = ActionResult(action="list_records", ok=True, records=[make("Купить хлеб")])
    assert focus_record_id(result) is None


def test_remember_focus_saves_single_hit_in_thread(monkeypatch):
    seen = {}

    def fake_save(db, conversation_id, user_id, record_id):
        seen["args"] = (db, conversation_id, user_id, record_id)
        seen["thread"] = threading.get_ident()

    monkeypatch.setattr(focus, "_save_focus", fake_save)
    record = make("Подписать договор")
    result = ActionResult(action="search_records", ok=True, records=[record])

    asyncio.run(remember_focus("db", "user", "conv", result))

    assert seen["args"] == ("db", "conv", "user", record.id)
    assert seen["thread"] != threading.get_ident()


def test_remember_focus_skips_when_no_single_hit(monkeypatch):
    called = []
    monkeypatch.setattr(focus, "_save_focus", lambda *args: called.append(args))
    result = ActionResult(action="search_records", ok=True, records=[make("A"), make("B")])

    asyncio.run(remember_focus("db", "user", "conv", result))

    assert called == []
