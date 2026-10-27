"""Цель изменения (agent-07, agent-09): `resolve_target` и заглушка `find_target`.

Тесты на тестовой PostgreSQL; без базы пропускаются, в CI выполняются.
"""

import asyncio
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from agent import targets as targets_module
from agent.targets import resolve_target
from db import models
from schemas import (
    ConversationState,
    RecordStatus,
    RecordType,
    SearchFilters,
    TargetMatch,
    TargetRef,
)
from services.search_stub import find_target

MSK = ZoneInfo("Europe/Moscow")
ACTIVE = [RecordStatus.ACTIVE]


def add(db: Session, user_id, title, start=None, *, type=None, status=RecordStatus.ACTIVE):
    # У встречи по правилам базы есть начало; без даты — задача.
    type = type or (RecordType.MEETING if start is not None else RecordType.TASK)
    row = models.Record(user_id=user_id, type=type, title=title, start=start,
                        all_day=False, status=status)
    db.add(row)
    db.flush()
    return row


def at(day, hour=0, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=MSK)


@pytest.fixture
def user_id():
    return uuid4()


def resolve(db, user_id, target, state=None, statuses=ACTIVE):
    state = state or ConversationState(conversation_id=uuid4(), user_id=user_id)
    return asyncio.run(resolve_target(db, user_id, target, state, statuses))


# --- заглушка find_target по контракту search.md ---

def test_find_target_needs_every_word_and_status(db: Session, user_id) -> None:
    ivan = add(db, user_id, "Встреча с Иваном", at(23, 15))
    add(db, user_id, "Встреча с дизайнером", at(23, 15))
    add(db, user_id, "Встреча с Иваном", at(22, 15), status=RecordStatus.CANCELLED)
    add(db, uuid4(), "Встреча с Иваном", at(23, 15))  # чужая

    match = find_target(db, user_id, "встреча Иваном", None, None, ACTIVE)
    assert [r.id for r in match.exact] == [ivan.id]
    assert match.similar == []


def test_find_target_narrows_by_when_then_falls_back_to_similar(db: Session, user_id) -> None:
    friday = add(db, user_id, "Встреча с дизайнером", at(23, 15))
    monday = add(db, user_id, "Встреча с дизайнером", at(26, 11))

    assert [r.id for r in find_target(db, user_id, "дизайнером", at(23), None,
                                      ACTIVE).exact] == [friday.id]
    assert [r.id for r in find_target(db, user_id, "дизайнером", at(30, 11), None,
                                      ACTIVE).exact] == [monday.id]  # то же время
    missed = find_target(db, user_id, "дизайнером", at(28), None, ACTIVE)
    assert missed.exact == []
    assert [r.id for r in missed.similar] == [friday.id, monday.id]


def test_find_target_without_text_takes_everything_by_filters(db: Session, user_id) -> None:
    calls = [add(db, user_id, f"Созвон {n}", at(22, 10 + n)) for n in range(3)]
    add(db, user_id, "Купить хлеб", at(22, 9), type=RecordType.TASK)
    filters = SearchFilters(types=[RecordType.MEETING], date_from=at(22), date_to=at(23))

    match = find_target(db, user_id, None, None, filters, ACTIVE)
    assert [r.id for r in match.exact] == [c.id for c in calls]


# --- resolve_target: index, focus, all, четыре исхода find_target ---

def test_index_and_focus_take_records_from_state(db: Session, user_id) -> None:
    first, second = add(db, user_id, "Первая"), add(db, user_id, "Вторая")
    state = ConversationState(conversation_id=uuid4(), user_id=user_id,
                              shown=[first.id, second.id], focus_record_id=first.id)

    assert resolve(db, user_id, TargetRef(index=2), state).records[0].id == second.id
    assert resolve(db, user_id, TargetRef(focus=True), state).records[0].id == first.id
    assert resolve(db, user_id, TargetRef(index=3), state).error == (
        "В показанном списке нет записи № 3.")
    no_focus = state.model_copy(update={"focus_record_id": None})
    assert resolve(db, user_id, TargetRef(focus=True), no_focus).error.startswith("Какую")


def test_foreign_record_in_shown_is_not_taken(db: Session, user_id) -> None:
    foreign = add(db, uuid4(), "Чужая")
    state = ConversationState(conversation_id=uuid4(), user_id=user_id, shown=[foreign.id])
    assert resolve(db, user_id, TargetRef(index=1), state).records == []


def test_all_without_description_takes_whole_screen(db: Session, user_id) -> None:
    rows = [add(db, user_id, f"Созвон {n}") for n in range(3)]
    state = ConversationState(conversation_id=uuid4(), user_id=user_id,
                              shown=[r.id for r in rows], awaiting="choice")
    target = resolve(db, user_id, TargetRef(all=True), state)
    assert [r.id for r in target.records] == [r.id for r in rows]


@pytest.mark.parametrize("exact, similar, outcome", [
    (1, 0, "records"), (2, 0, "candidates"), (0, 2, "similar"), (0, 0, "error"),
])
def test_four_outcomes_of_find_target(db: Session, user_id, monkeypatch,
                                      exact, similar, outcome) -> None:
    rows = [add(db, user_id, f"Запись {n}") for n in range(4)]
    from schemas import Record
    records = [Record.model_validate(r) for r in rows]
    match = TargetMatch(exact=records[:exact], similar=records[2:2 + similar])
    monkeypatch.setattr(targets_module, "find_target", lambda *args: match)

    target = resolve(db, user_id, TargetRef(text="встречу с дизайнером"))
    if outcome == "records":
        assert target.records == records[:1] and not target.candidates
    elif outcome == "candidates":
        assert target.candidates == records[:2] and not target.similar and not target.records
    elif outcome == "similar":
        # Похожие только предлагаются: исполнять их без ответа нельзя.
        assert target.similar and target.candidates == records[2:4] and not target.records
    else:
        assert target.error == "Не нашёл «встречу с дизайнером»."


def test_all_takes_only_exact_and_limits_to_twenty(db: Session, user_id, monkeypatch) -> None:
    from schemas import Record
    many = [Record.model_validate(add(db, user_id, f"Созвон {n}")) for n in range(21)]
    calls = []

    def fake(*args):
        calls.append(args)
        return TargetMatch(exact=many[:fake.count], similar=many[:2])

    monkeypatch.setattr(targets_module, "find_target", fake)
    target_ref = TargetRef(all=True, text="созвоны")

    fake.count = 21
    assert resolve(db, user_id, target_ref).error.startswith("Слишком много")
    assert calls[0][-1] == 21  # limit=21: «больше 20» видно по 21-й записи
    fake.count = 3
    three = resolve(db, user_id, target_ref)
    assert three.confirm and three.candidates == many[:3] and not three.records
    fake.count = 1
    assert resolve(db, user_id, target_ref).records == many[:1]  # одна — сразу
    fake.count = 0
    assert resolve(db, user_id, target_ref).error.startswith("Не нашёл")  # похожие не берём


def test_statuses_are_passed_to_find_target(db: Session, user_id, monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(targets_module, "find_target",
                        lambda *args: seen.append(args[5]) or TargetMatch())
    statuses = [RecordStatus.DONE, RecordStatus.CANCELLED]
    resolve(db, user_id, TargetRef(text="отчёт"), statuses=statuses)
    assert seen == [statuses]


def test_target_stems_drop_type_words_and_endings() -> None:
    from services.search_stub import target_stems

    assert target_stems("встречу с Иваном") == ["иван"]
    assert target_stems("созвон с Севером по CRM") == ["созв", "север", "crm"]


def test_stub_never_takes_other_record_for_crm(db: Session, user_id) -> None:
    """«Отмени созвон с Севером по CRM» не находит «…по новому продукту» точно."""
    add(db, user_id, "Созвон с Севером по новому продукту", at(22, 12))
    match = find_target(db, user_id, "созвон с Севером по CRM", None, None, ACTIVE)
    assert match.exact == []
