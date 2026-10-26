"""Прогон кейсов (agent-08) со сценарием вместо модели: без сети, в CI."""

from datetime import datetime

from schemas import AskUser, CreateRecord, ListRecords
from tests.agent_cases import CASES, Case, Expect, Turn
from tests.agent_live import TZ, Harness, render, select_cases


def case(id_: str) -> Case:
    return next(c for c in CASES if c.id == id_)


def scripted(*actions):
    queue = list(actions)

    async def model(*args, **kwargs):
        return queue.pop(0)

    return model


def test_single_turn_passes_and_fails(monkeypatch):
    good = CreateRecord(type="reminder", title="позвонить Ивану",
                        start=datetime(2026, 10, 22, 10, tzinfo=TZ), time_given=True)
    bad = good.model_copy(update={"start": datetime(2026, 10, 23, 10, tzinfo=TZ)})
    harness = Harness(monkeypatch, scripted(good, bad))

    assert harness.run_case(case("1.1")).passed
    failed = harness.run_case(case("1.1"))
    assert not failed.passed
    assert "start" in failed.turns[0].problems[0]


def test_dialog_fills_draft_and_creates(monkeypatch):
    first = CreateRecord(type="meeting", title="встреча с Иваном",
                         start=datetime(2026, 10, 22, tzinfo=TZ), time_given=False)
    second = first.model_copy(update={
        "start": datetime(2026, 10, 22, 15, tzinfo=TZ), "time_given": True,
    })
    report = Harness(monkeypatch, scripted(first, second)).run_case(case("1.15"))
    assert report.passed, [t.problems for t in report.turns]
    assert report.turns[0].observed.awaiting == "answer"
    assert report.turns[1].observed.ok is True


def test_date_in_past_is_rejected_by_business_rules(monkeypatch):
    past = CreateRecord(type="reminder", title="позвонить Ивану",
                        start=datetime(2026, 10, 20, tzinfo=TZ), time_given=False)
    assert Harness(monkeypatch, scripted(past)).run_case(case("8.3")).passed


def test_question_without_execution(monkeypatch):
    ask = AskUser(question="Что добавить?", missing=["title"])
    report = Harness(monkeypatch, scripted(ask)).run_case(Case(
        id="x", turns=(Turn("Добавь встречу", Expect(action="ask_user", awaiting="answer")),),
    ))
    assert report.passed


def test_report_lists_failed_cases(monkeypatch):
    wrong = ListRecords(date_from=datetime(2026, 10, 21, tzinfo=TZ),
                        date_to=datetime(2026, 10, 22, tzinfo=TZ))
    report = Harness(monkeypatch, scripted(wrong)).run_case(case("4.1"))
    text = render([report], skipped=[case("7.1")])
    assert "прошло 0 из 1" in text
    assert "УПАЛ 4.1" in text
    assert "пропущено с причиной: 1" in text


def test_select_sections():
    assert {c.section for c in select_cases("2, 3")} == {"2", "3"}
    assert len(select_cases(None)) == len(CASES)


def test_every_case_runs_without_crash(monkeypatch):
    """Прогон всех кейсов не падает с исключением, даже если модель отвечает невпопад."""
    from schemas import Help

    async def model(*args, **kwargs):
        return Help(kind="offtopic")

    harness = Harness(monkeypatch, model)
    reports = [harness.run_case(c) for c in CASES if c.skip is None]
    assert reports and all(r.turns for r in reports)
