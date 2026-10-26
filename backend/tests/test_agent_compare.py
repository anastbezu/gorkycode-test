"""Сравниватель автотеста: ожидание кейса против действия модели (без сети и базы)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from schemas import AskUser, CreateRecord, Help, ListRecords, SearchFilters, SearchRecords
from tests.agent_cases import ALL, NONE, Expect
from tests.agent_compare import Observed, compare, describe

MSK = ZoneInfo("Europe/Moscow")


def at(*args) -> datetime:
    return datetime(*args, tzinfo=MSK)


def check(expect: Expect, action, **kwargs) -> list[str]:
    return compare(expect, Observed(action=action, **kwargs), MSK)


def test_same_moment_in_other_zone_passes():
    action = CreateRecord(
        type="reminder", title="Позвонить Ивану по поводу договора",
        start=datetime(2026, 10, 22, 7, 0, tzinfo=UTC), time_given=True,
    )
    expect = Expect(action="create_record", type="reminder", title=("позвон", "Иван"),
                    start="2026-10-22 10:00")
    assert check(expect, action) == []


def test_seconds_are_ignored_but_minutes_are_not():
    expect = Expect(action="create_record", deadline="2026-10-25 23:59")
    ok = CreateRecord(type="task", title="x", deadline=at(2026, 10, 25, 23, 59, 59),
                      time_given=False)
    wrong = CreateRecord(type="task", title="x", deadline=at(2026, 10, 25, 23, 0),
                         time_given=False)
    assert check(expect, ok) == []
    assert check(expect, wrong) != []


def test_date_only_requires_time_not_given():
    expect = Expect(action="create_record", start="2026-10-23")
    all_day = CreateRecord(type="task", title="x", start=at(2026, 10, 23), time_given=False)
    midnight = CreateRecord(type="task", title="x", start=at(2026, 10, 23), time_given=True)
    assert check(expect, all_day) == []
    assert any("time_given" in p for p in check(expect, midnight))


def test_none_means_field_is_empty():
    expect = Expect(action="create_record", start=NONE, deadline=NONE)
    assert check(expect, CreateRecord(type="task", title="x", time_given=False)) == []
    dated = CreateRecord(type="task", title="x", start=at(2026, 10, 22), time_given=False)
    assert check(expect, dated) != []


def test_wrong_action_stops_comparison():
    expect = Expect(action="create_record", type="task", start="2026-10-22")
    problems = check(expect, Help(kind="help"))
    assert problems == ["действие: ожидалось create_record, получено help"]


def test_action_alternatives_and_awaiting():
    expect = Expect(action="create_record|ask_user", awaiting="answer")
    question = AskUser(question="На какое время?", missing=["start"])
    assert check(expect, question, awaiting="answer") == []
    assert check(expect, question, awaiting=None) != []


def test_list_types_all_and_subset():
    week = ListRecords(date_from=at(2026, 10, 19), date_to=at(2026, 10, 26))
    expect_all = Expect(action="list_records", date_from="2026-10-19 00:00",
                        date_to="2026-10-26 00:00", types=ALL)
    assert check(expect_all, week) == []
    tasks = week.model_copy(update={"types": ["reminder", "task"]})
    assert check(Expect(action="list_records", types=("task", "reminder")), tasks) == []
    assert check(Expect(action="list_records", types=("task", "reminder")), week) != []


def test_title_words_with_alternatives():
    action = CreateRecord(type="meeting", title="Планерка по CRM", start=at(2026, 10, 23, 10),
                          time_given=True)
    assert check(Expect(action="create_record", title=("планёрк|планерк", "crm")), action) == []
    assert check(Expect(action="create_record", title=("сайт",)), action) != []


def test_search_query_and_filters():
    action = SearchRecords(query="планёрка по CRM", filters=SearchFilters(
        date_from=at(2026, 10, 12), date_to=at(2026, 10, 19),
    ))
    expect = Expect(action="search_records", query=("CRM",),
                    query_from="2026-10-12 00:00", query_to="2026-10-19 00:00")
    assert check(expect, action) == []
    no_dates = Expect(action="search_records", query_from=NONE, query_to=NONE)
    assert check(no_dates, action) != []
    assert check(no_dates, SearchRecords(query="договор")) == []


def test_execution_result_is_checked():
    action = CreateRecord(type="reminder", title="x", start=at(2026, 10, 20, 10), time_given=True)
    assert check(Expect(action="create_record", ok=False), action, ok=False) == []
    assert check(Expect(action="create_record", ok=False), action, ok=True) != []


def test_describe_shows_local_time():
    action = CreateRecord(type="task", title="x", start=datetime(2026, 10, 22, 7, tzinfo=UTC),
                          time_given=True)
    assert "start=2026-10-22 10:00" in describe(action, MSK)
