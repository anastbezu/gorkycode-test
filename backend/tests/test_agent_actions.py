import asyncio
import threading
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent import actions
from schemas import ActionResult, CreateRecord, ListRecords, Record, SearchHit, SearchRecords

MSK = ZoneInfo("Europe/Moscow")


def test_list_handler_calls_service_in_thread(monkeypatch):
    seen = {}

    def fake_service(db, user_id, action):
        seen["thread"] = threading.get_ident()
        seen["args"] = (db, user_id, action)
        return ActionResult(action="list_records", ok=True, records=[])

    monkeypatch.setattr("agent.actions.list_records_for_period", fake_service)
    action = ListRecords(
        date_from=datetime(2026, 10, 26, 0, 0, tzinfo=MSK),
        date_to=datetime(2026, 10, 27, 0, 0, tzinfo=MSK),
    )

    result = asyncio.run(actions.handle_list_records("db", "user", action))

    assert result.ok
    assert seen["args"] == ("db", "user", action)
    assert seen["thread"] != threading.get_ident()


def test_search_handler_calls_stub_in_thread(monkeypatch):
    seen = {}
    record = Record(id=uuid4(), user_id=uuid4(), type="task", title="Подписать договор",
                    created_at=datetime(2026, 10, 25, tzinfo=MSK))

    def fake_search(db, user_id, query, filters):
        seen["thread"] = threading.get_ident()
        seen["args"] = (db, user_id, query)
        return [SearchHit(record=record, score=1.0)]

    monkeypatch.setattr("agent.actions.search_by_substring", fake_search)
    action = SearchRecords(query="договор")

    result = asyncio.run(actions.handle_search_records("db", "user", action))

    assert result.ok
    assert result.records == [record]
    assert seen["args"] == ("db", "user", "договор")
    assert seen["thread"] != threading.get_ident()


def test_create_handler_passes_now_to_service(monkeypatch):
    seen = {}

    def fake_create(db, user_id, action, *, now=None):
        seen["now"] = now
        return ActionResult(action="create_record", ok=True, records=[])

    monkeypatch.setattr("agent.actions.create_record", fake_create)
    now = datetime(2026, 10, 21, 10, 0, tzinfo=MSK)
    action = CreateRecord(type="task", title="купить хлеб", time_given=False)

    asyncio.run(actions.handle_create_record("db", "user", action, now=now))

    assert seen["now"] == now