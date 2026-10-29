"""Быстрый слой автотеста на тестовой PostgreSQL (agent-08): модель — сценарий, всё
остальное настоящее — `process_user_turn`, сервисы записей и состояние разговора.
Без базы тесты пропускаются, в CI выполняются."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import models
from eval.cases import CASES
from eval.compare import compare
from eval.harness import TZ, Harness
from schemas import CreateRecord
from services import get_conversation_state


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


def test_ask_with_draft_keeps_reminder_time_3_5(db: Session, monkeypatch) -> None:
    from schemas import AskDraft, AskUser

    ask = AskUser(question="О чём напомнить?", missing=["title"], draft=AskDraft(
        type="reminder", start=datetime(2026, 10, 22, 10, tzinfo=TZ), time_given=True))
    # Модель на ответе забыла тип и время: они есть только в draft.
    answer = CreateRecord(type="task", title="позвонить маме", time_given=False)
    harness = Harness(monkeypatch, scripted(ask, answer), db=db)
    user_id, conversation_id = uuid4(), uuid4()

    observed, _ = harness.run_turn("Напомни завтра в 10", user_id, conversation_id)
    assert compare(expect("3.5", 0), observed, TZ) == []
    observed, _ = harness.run_turn("Позвонить маме", user_id, conversation_id)
    assert compare(expect("3.5", 1), observed, TZ) == []
    [row] = records(db, user_id)
    assert (row.type, row.start, row.all_day) == ("reminder", datetime(2026, 10, 22, 10,
                                                                        tzinfo=TZ), False)
    assert get_conversation_state(db, conversation_id, user_id).pending is None


def test_meeting_time_without_day_asks_day_3_8(db: Session, monkeypatch) -> None:
    from schemas import AskDraft, AskUser

    ask = AskUser(question="На какой день?", missing=["start"], draft=AskDraft(
        type="meeting", title="встреча с Сергеем", time="14:45"))
    answer = CreateRecord(type="meeting", title="встреча с Сергеем",
                          start=datetime(2026, 10, 22, tzinfo=TZ), time_given=False)
    harness = Harness(monkeypatch, scripted(ask, answer), db=db)
    user_id, conversation_id = uuid4(), uuid4()

    observed, _ = harness.run_turn("Встреча с Сергеем в 14:45", user_id, conversation_id)
    assert compare(expect("3.8", 0), observed, TZ) == []
    observed, _ = harness.run_turn("Завтра", user_id, conversation_id)
    assert compare(expect("3.8", 1), observed, TZ) == []
    [row] = records(db, user_id)
    assert row.start == datetime(2026, 10, 22, 14, 45, tzinfo=TZ)
    assert row.all_day is False


# --- Раздел 7 и пересечения: «идеальная модель» проходит кейсы на настоящем коде -----------
# Если кейс здесь падает, расходятся ожидание в наборе test-cases.json и код агента, а не модель.

def _ideal_model_actions() -> dict:
    import pytest as _pytest  # noqa: F401  (только чтобы файл не терял импорты при правке)

    from schemas import (
        AskUser,
        ListRecords,
        SearchFilters,
        SetStatus,
        TargetRef,
        UndoLast,
        UpdateRecord,
    )

    def at(day, hour=0, minute=0):
        return datetime(2026, 10, day, hour, minute, tzinfo=TZ)

    def status(value, **target):
        return SetStatus(target=TargetRef(**target), status=value)

    def move(start, **target):
        return UpdateRecord(target=TargetRef(**target), start=start, time_given=True)

    def shift(minutes, **target):
        return UpdateRecord(target=TargetRef(**target), shift_minutes=minutes)

    tomorrow = ListRecords(date_from=at(22), date_to=at(23))
    team = CreateRecord(type="meeting", title="встреча с командой", start=at(22, 15),
                        time_given=True)
    natalia = CreateRecord(type="meeting", title="встреча с Натальей по презентации",
                           start=at(27, 16, 30), time_given=True)
    bank = CreateRecord(type="reminder", title="позвонить в банк", start=at(22, 10),
                        time_given=True)
    vector = status("cancelled", text="созвон с Вектором по интеграции")
    all_tomorrow = status("cancelled", all=True, filters=SearchFilters(
        date_from=at(22), date_to=at(23)))
    return {
        "1.16": [natalia, move(at(22, 16, 30), focus=True)],
        "7.1": [move(at(23, 15), text="встречу с Иваном")],
        "7.2": [status("done", text="задачу про отчёт"), status("done", index=1)],
        "7.3": [status("cancelled", text="созвон с Вектором"), status("cancelled", index=2)],
        "7.4": [tomorrow, move(at(23, 12), index=2)],
        "7.5": [team, shift(60, focus=True)],
        "7.6": [status("done", text="позвонить Ольге")],
        "7.7": [status("cancelled", text="задачу про договор")],
        "7.8": [status("cancelled", text="задачу про отчёт")],
        "7.9": [AskUser(question="Что отметить?", missing=["target"])],
        "7.10": [bank, status("cancelled", focus=True)],
        "7.11": [team, move(at(22, 16), focus=True)],
        "7.12": [status("cancelled", text="встречу с дизайнером")],
        "7.13": [status("cancelled", text="встречу с дизайнером"), UndoLast()],
        "7.14": [vector],
        "7.15": [vector, SetStatus(target=TargetRef(text="созвон по сайту"),
                                   status="cancelled", replaces_last=True)],
        "7.16": [tomorrow, move(at(22, 16), focus=True)],
        "7.17": [shift(60, text="встречу с Натальей")],
        "7.18": [shift(60, text="встречу с Натальей"), UndoLast()],
        "7.19": [all_tomorrow],
        "7.20": [all_tomorrow, status("cancelled", all=True)],
        "7.21": [all_tomorrow, status("cancelled", all=True), UndoLast()],
        "7.22": [status("cancelled", all=True, text="созвон", filters=SearchFilters(
            types=["meeting"], date_from=at(19), date_to=at(26)))],
        "8.5": [CreateRecord(type="meeting", title="встреча с Анной", start=at(22, 12),
                             time_given=True)],
        "8.7": [CreateRecord(type="meeting", title="встреча с Анной", start=at(22, 12, 30),
                             time_given=True)],
        "8.8": [CreateRecord(type="meeting", title="Созвон с Альфой по бюджету",
                             start=at(22, 12), time_given=True)],
    }


def test_cases_with_records_pass_on_ideal_model(db: Session, monkeypatch) -> None:
    ideal = _ideal_model_actions()
    db_cases = [c for c in CASES if c.needs_db and c.skip is None]
    assert sorted(c.id for c in db_cases) == sorted(ideal), "у кейса с базой нет сценария"
    failed = {}
    for case in db_cases:
        harness = Harness(monkeypatch, scripted(*ideal[case.id]), db=db)
        report = harness.run_case(case)
        if not report.passed:
            turn = report.turns[-1]
            failed[case.id] = (turn.number, turn.reply, turn.problems)
    assert failed == {}


def test_harness_sees_applied_change_not_raw_model_answer(db: Session, monkeypatch) -> None:
    """Живой прогон 27.10: модель ошиблась, код поправил — автотест сверяет исполненное."""
    from schemas import TargetRef, UpdateRecord

    def case(case_id):
        return next(c for c in CASES if c.id == case_id)

    midnight = UpdateRecord(target=TargetRef(text="встречу с Иваном"),
                            start=datetime(2026, 10, 23, tzinfo=TZ))
    report = Harness(monkeypatch, scripted(midnight), db=db).run_case(case("7.1"))
    assert report.passed, report.turns[-1].problems

    later = UpdateRecord(target=TargetRef(text="встречу с Натальей"), shift_minutes=60)
    report = Harness(monkeypatch, scripted(later), db=db).run_case(case("7.17"))
    assert report.passed, report.turns[-1].problems
