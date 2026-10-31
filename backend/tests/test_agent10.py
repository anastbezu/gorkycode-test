"""Быстрые ответы (agent-10): чего ждёт сервер — выбора, подтверждения или времени встречи.

Модель — сценарий (подменённый `get_action`), всё остальное настоящее: `process_user_turn`,
поиск цели, сервисы записей и состояние разговора. Без базы тесты пропускаются.
"""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_agent_changes_db import Dialog, at, cancel

from agent import agent as agent_module
from alembic import command, config
from db import models
from schemas import (
    AskDraft,
    AskUser,
    ConversationState,
    CreateRecord,
    RecordStatus,
    RecordType,
    TargetRef,
    UpdateRecord,
)
from services import save_conversation_state

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def dialog(db: Session, monkeypatch):
    return Dialog(db, monkeypatch)


def no_model(monkeypatch) -> None:
    """Модель вызывать нельзя: «номер N» разбирает код."""

    async def fail(*args, **kwargs):
        raise AssertionError("модель не должна вызываться")

    monkeypatch.setattr(agent_module, "get_action", fail)


def meetings(dialog: Dialog, count: int) -> list[models.Record]:
    return [dialog.add(f"Созвон {n}", at(22, 10 + n)) for n in range(count)]


# --- подтверждение массового действия -----------------------------------------------------


def test_mass_cancel_asks_confirm_and_yes_cancels_all(dialog) -> None:
    calls = meetings(dialog, 3)

    response = dialog.say("Отмени все созвоны", cancel(all=True, text="созвоны"))

    assert response.awaiting == "confirm"
    assert [r.id for r in response.result.candidates] == [c.id for c in calls]
    assert all(dialog.row(c).status == RecordStatus.ACTIVE for c in calls)

    response = dialog.say("да, все", cancel(all=True))

    assert all(dialog.row(c).status == RecordStatus.CANCELLED for c in calls)
    assert response.awaiting is None
    assert dialog.state().awaiting is None


def test_refusal_on_confirm_changes_nothing(dialog, monkeypatch) -> None:
    calls = meetings(dialog, 3)
    dialog.say("Отмени все созвоны", cancel(all=True, text="созвоны"))
    no_model(monkeypatch)  # «отмена» — отказ без модели

    response = dialog.say("отмена")

    assert response.awaiting is None
    assert all(dialog.row(c).status == RecordStatus.ACTIVE for c in calls)
    state = dialog.state()
    assert state.awaiting is None and state.pending is None and state.candidates == []


def test_number_on_confirm_takes_only_that_record(dialog, monkeypatch) -> None:
    calls = meetings(dialog, 3)
    dialog.say("Отмени все созвоны", cancel(all=True, text="созвоны"))
    no_model(monkeypatch)

    response = dialog.say("номер 2")

    assert response.awaiting is None
    assert [dialog.row(c).status for c in calls] == [
        RecordStatus.ACTIVE,
        RecordStatus.CANCELLED,
        RecordStatus.ACTIVE,
    ]


# --- выбор одной записи: «номер N» без модели ---------------------------------------------


def _two_meetings_to_move(dialog: Dialog):
    first = dialog.add("Встреча с Иваном", at(22, 15))
    second = dialog.add("Встреча с Иваном", at(27, 8, 45))
    move = UpdateRecord(target=TargetRef(text="встречу с Иваном"), shift_minutes=60)
    response = dialog.say("Перенеси встречу с Иваном на час позже", move)
    assert response.awaiting == "choice"
    return first, second


@pytest.mark.parametrize("answer", ["номер 2", "Номер 2.", "  НОМЕР  2!  "])
def test_number_chooses_without_model(dialog, monkeypatch, answer: str) -> None:
    first, second = _two_meetings_to_move(dialog)
    no_model(monkeypatch)

    response = dialog.say(answer)

    assert response.awaiting is None
    assert dialog.row(second).start == at(27, 9, 45)  # перенесена вторая
    assert dialog.row(first).start == at(22, 15)
    state = dialog.state()
    assert state.pending is None and state.candidates == []
    assert state.last_action.record_ids == [second.id]  # «верни» откатит именно её


def test_number_out_of_range_keeps_waiting(dialog, monkeypatch) -> None:
    first, second = _two_meetings_to_move(dialog)
    no_model(monkeypatch)

    response = dialog.say("номер 5")

    assert response.reply == "Нет записи под номером 5."
    assert response.awaiting == "choice"
    # Кандидаты снова в ответе — интерфейс показывает тот же список и чипы.
    assert [r.id for r in response.result.candidates] == [first.id, second.id]
    assert dialog.row(first).start == at(22, 15) and dialog.row(second).start == at(27, 8, 45)
    state = dialog.state()
    assert state.awaiting == "choice" and state.candidates == [first.id, second.id]

    dialog.say("номер 1")  # ожидание осталось — выбор работает дальше
    assert dialog.row(first).start == at(22, 16)


def test_number_without_waiting_goes_to_model(dialog) -> None:
    """Без выбора «номер 2» — обычная реплика: её разбирает модель."""
    dialog.add("Встреча с Иваном", at(22, 15))
    move = UpdateRecord(target=TargetRef(index=2), shift_minutes=30)

    dialog.say("номер 2", move)

    assert dialog.actions == []  # сценарий модели использован — модель вызывалась


# --- время встречи ------------------------------------------------------------------------


def test_meeting_with_day_waits_for_time_then_created(dialog) -> None:
    tomorrow = CreateRecord(
        type=RecordType.MEETING, title="встреча с Игорем", start=at(22), time_given=False
    )

    response = dialog.say("Назначь встречу с Игорем завтра", tomorrow)

    assert response.awaiting == "time"
    assert response.result.missing == ["start"]

    answer = tomorrow.model_copy(update={"start": at(22, 15), "time_given": True})
    response = dialog.say("в 15:00", answer)

    assert response.awaiting is None
    assert response.result.ok
    created = response.result.records[0]
    assert created.title == "встреча с Игорем" and created.start == at(22, 15)


def test_question_with_meeting_draft_waits_for_time(dialog) -> None:
    ask = AskUser(
        question="На какое время поставить встречу?",
        missing=["start"],
        draft=AskDraft(
            type=RecordType.MEETING, title="встреча с Игорем", start=at(22), time_given=False
        ),
    )

    assert dialog.say("Назначь встречу с Игорем завтра", ask).awaiting == "time"

    answer = CreateRecord(
        type=RecordType.MEETING, title="встреча с Игорем", start=at(22, 15), time_given=True
    )
    response = dialog.say("в 15:00", answer)
    assert response.result.ok and response.result.records[0].start == at(22, 15)


@pytest.mark.parametrize(
    "ask",
    [
        # Нет названия — спрашиваем, что поставить.
        AskUser(question="Что поставить?", missing=["title"]),
        # Время есть, дня нет — спрашиваем день.
        AskUser(
            question="На какой день?",
            missing=["start"],
            draft=AskDraft(type=RecordType.MEETING, title="встреча с Сергеем", time="14:45"),
        ),
        # Не встреча: задаче время не обязательно.
        AskUser(
            question="Когда напомнить?",
            missing=["start"],
            draft=AskDraft(type=RecordType.REMINDER, title="позвонить маме", start=at(22)),
        ),
    ],
)
def test_other_questions_wait_for_answer(dialog, ask: AskUser) -> None:
    assert dialog.say("…", ask).awaiting == "answer"


def test_meeting_without_day_waits_for_answer(dialog) -> None:
    no_day = CreateRecord(type=RecordType.MEETING, title="встреча с Дмитрием", time_given=False)

    assert dialog.say("Поставь встречу с Дмитрием", no_day).awaiting == "answer"


# --- база ---------------------------------------------------------------------------------


@pytest.mark.parametrize("awaiting", ["answer", "choice", "confirm", "time"])
def test_db_accepts_all_awaiting_values(db: Session, awaiting: str) -> None:
    state = ConversationState(conversation_id=uuid4(), user_id=uuid4(), awaiting=awaiting)
    db.add(models.ConversationState(conversation_id=state.conversation_id, user_id=state.user_id))
    db.flush()

    save_conversation_state(db, state)

    row = db.get(models.ConversationState, state.conversation_id)
    db.refresh(row)
    assert row.awaiting == awaiting


def test_db_rejects_unknown_awaiting(db: Session) -> None:
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text(
                "INSERT INTO conversation_states (conversation_id, user_id, awaiting) "
                "VALUES (:c, :u, 'maybe')"
            ),
            {"c": uuid4(), "u": uuid4()},
        )


def test_migration_0006_down_and_up(engine: Engine) -> None:
    cfg = config.Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    insert = text(
        "INSERT INTO conversation_states (conversation_id, user_id, awaiting) "
        "VALUES (:c, :u, 'confirm')"
    )
    try:
        command.downgrade(cfg, "0005")
        with engine.connect() as conn, pytest.raises(IntegrityError):
            conn.execute(insert, {"c": uuid4(), "u": uuid4()})
    finally:
        command.upgrade(cfg, "head")
    with engine.connect() as conn:
        conn.execute(insert, {"c": uuid4(), "u": uuid4()})
        conn.rollback()
