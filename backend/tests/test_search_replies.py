from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent.replies import reply_for_result
from agent.search_replies import reply_for_search
from schemas import ActionResult, Record, SearchRecords

TZ = "Europe/Moscow"
MSK = ZoneInfo(TZ)
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=MSK)


def make(title, start=None, all_day=False, deadline=None):
    return Record(id=uuid4(), user_id=uuid4(), type="task", title=title, start=start,
                  all_day=all_day, deadline=deadline, created_at=NOW)


def test_nothing_found_suggests_other_words():
    reply = reply_for_search([], "договор", TZ, NOW)
    assert reply == "По запросу «договор» ничего не нашлось. Попробуйте другие слова."


def test_single_record_names_date_and_time():
    start = datetime(2026, 8, 22, 20, 30, tzinfo=MSK)
    records = [make("Подписать договор", start=start)]
    reply = reply_for_search(records, "договор", TZ, NOW)
    assert reply == "«Подписать договор» — 22 августа, в 20:30."


def test_several_records_keep_result_order_without_numbers():
    records = [
        make("Старый договор", start=datetime(2025, 3, 1, 10, 0, tzinfo=MSK)),
        make("Свежий договор", start=datetime(2026, 10, 20, 9, 0, tzinfo=MSK)),
        make("Средний договор", start=datetime(2026, 6, 1, 9, 0, tzinfo=MSK)),
    ]
    reply = reply_for_search(records, "договор", TZ, NOW)
    assert reply.startswith("Нашёл 3 записи.")
    assert "Свежий договор" in reply
    assert "20 октября, в 09:00" in reply
    assert reply.index("«Старый") < reply.index("«Свежий") < reply.index("«Средний")
    assert "1)" not in reply  # номера — только на экране


def test_all_day_record_has_no_time():
    records = [make("Купить хлеб", start=datetime(2026, 10, 24, 0, 0, tzinfo=MSK), all_day=True)]
    reply = reply_for_search(records, "хлеб", TZ, NOW)
    assert reply == "«Купить хлеб» — вчера."
    assert "00:00" not in reply


def test_other_year_is_named():
    records = [make("Налоги", start=datetime(2025, 11, 22, 20, 30, tzinfo=MSK))]
    assert "22 ноября 2025 года" in reply_for_search(records, "налоги", TZ, NOW)


def test_reply_for_result_uses_search_reply():
    result = ActionResult(action="search_records", ok=True, records=[])
    reply = reply_for_result(result, TZ, action=SearchRecords(query="договор"), now=NOW)
    assert "ничего не нашлось" in reply


def test_repeated_title_is_grouped_with_latest_representative():
    records = [
        make("Созвон с юристами", start=datetime(2026, 9, 1, 10, 0, tzinfo=MSK)),
        make("Созвон с юристами", start=datetime(2026, 11, 20, 11, 0, tzinfo=MSK)),
        make("Созвон с юристами", start=datetime(2026, 10, 26, 11, 0, tzinfo=MSK)),
    ]
    reply = reply_for_search(records, "созвон юристы", TZ, NOW)
    assert "Созвон с юристами — 3 раза, последний 20.11.2026" in reply


def test_similar_hits_say_not_found_exactly_and_list_similar(monkeypatch):
    """agent-09: search() отдал только похожие — «Точно не нашёл …. Похожие: …»."""
    import asyncio

    from agent import actions as actions_module
    from schemas import SearchFilters, SearchHit

    lease = make("Договор поставки", start=datetime(2026, 10, 26, 15, 0, tzinfo=MSK))
    monkeypatch.setattr(actions_module, "search_by_substring", lambda *args: [
        SearchHit(record=lease, score=0.7, match="similar")])
    action = SearchRecords(query="договор аренды", filters=SearchFilters())
    result = asyncio.run(actions_module.execute(None, uuid4(), action, now=NOW))

    assert result.records == [lease]
    reply = reply_for_result(result, TZ, action=action, now=NOW)
    assert reply == (
        "Точно не нашёл «договор аренды». Похожие: «Договор поставки» — завтра, в 15:00."
    )
    # Наружу (ChatResponse.result: ActionResult) признак не уходит — контракт API прежний.
    from schemas import ChatResponse

    response = ChatResponse(conversation_id=uuid4(), reply=reply, result=result)
    assert "similar" not in response.model_dump()["result"]
    assert "similar" not in response.model_dump_json()


def test_exact_hits_reply_as_before(monkeypatch):
    import asyncio

    from agent import actions as actions_module
    from schemas import SearchFilters, SearchHit

    record = make("Договор аренды", start=datetime(2026, 10, 26, 15, 0, tzinfo=MSK))
    monkeypatch.setattr(actions_module, "search_by_substring", lambda *args: [
        SearchHit(record=record, score=1.0)])
    action = SearchRecords(query="договор аренды", filters=SearchFilters())
    result = asyncio.run(actions_module.execute(None, uuid4(), action, now=NOW))
    assert reply_for_result(result, TZ, action=action, now=NOW) == (
        "«Договор аренды» — завтра, в 15:00.")
