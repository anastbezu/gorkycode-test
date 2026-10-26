from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent.list_replies import reply_for_list
from agent.replies import reply_for_result
from schemas import ActionResult, ListRecords, Record

TZ = "Europe/Moscow"
MSK = ZoneInfo(TZ)
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=MSK)  # воскресенье

TOMORROW = ListRecords(
    date_from=datetime(2026, 10, 26, 0, 0, tzinfo=MSK),
    date_to=datetime(2026, 10, 27, 0, 0, tzinfo=MSK),
)
WEEK = ListRecords(
    date_from=datetime(2026, 10, 26, 0, 0, tzinfo=MSK),
    date_to=datetime(2026, 11, 2, 0, 0, tzinfo=MSK),
)


def make(type_, title, start=None, all_day=False, deadline=None):
    return Record(id=uuid4(), user_id=uuid4(), type=type_, title=title,
                  start=start, all_day=all_day, deadline=deadline, created_at=NOW)


def test_two_records_audible_reply():
    records = [
        make("task", "Купить хлеб", start=datetime(2026, 10, 26, 0, 0, tzinfo=MSK), all_day=True),
        make("meeting", "Встреча с командой", start=datetime(2026, 10, 26, 15, 0, tzinfo=MSK)),
    ]
    reply = reply_for_list(records, TOMORROW, TZ, NOW)
    assert "На завтра" in reply
    assert "2 дела" in reply
    assert "15:00" in reply
    assert "купить хлеб" in reply
    assert "00:00" not in reply


def test_empty_list_is_polite():
    assert reply_for_list([], TOMORROW, TZ, NOW) == "На завтра ничего не запланировано."


def test_single_record():
    start = datetime(2026, 10, 26, 11, 30, tzinfo=MSK)
    records = [make("meeting", "Созвон с юристами", start=start)]
    reply = reply_for_list(records, TOMORROW, TZ, NOW)
    assert reply == "На завтра одно дело: 11:30 — созвон с юристами."


def test_long_list_is_shortened():
    records = [make("task", f"Дело {i}", start=datetime(2026, 10, 26, 9 + i, 0, tzinfo=MSK))
               for i in range(5)]
    reply = reply_for_list(records, TOMORROW, TZ, NOW)
    assert "5 дел" in reply
    assert "Остальные на экране" in reply
    assert reply.count("—") == 3  # вслух только три пункта


def test_multi_day_period_names_days():
    records = [make("meeting", "Планёрка", start=datetime(2026, 10, 30, 10, 0, tzinfo=MSK))]
    reply = reply_for_list(records, WEEK, TZ, NOW)
    assert reply.startswith("С 26 октября по 1 ноября")
    assert "в пятницу в 10:00" in reply


def test_reply_for_result_uses_list_reply():
    records = [make("meeting", "Планёрка", start=datetime(2026, 10, 26, 10, 0, tzinfo=MSK))]
    result = ActionResult(action="list_records", ok=True, records=records)
    reply = reply_for_result(result, TZ, action=TOMORROW, now=NOW)
    assert reply == "На завтра одно дело: 10:00 — планёрка."
