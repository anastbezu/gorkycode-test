from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent.focus import focus_record_id
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


def test_list_with_one_record_becomes_focus():
    result = ActionResult(action="list_records", ok=True, records=[make("Купить хлеб")])
    assert focus_record_id(result) == result.records[0].id


def test_compatibility_import_uses_common_state_logic():
    from agent.state import focus_record_id as common

    assert focus_record_id is common
