"""backend-03: изменение и статус записей, откат, конфликты и дубль, список без конца периода,
новые поля состояния, один коммит на реплику. Тесты с базой — пропускаются без DATABASE_URL."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from db import get_session, models
from main import app
from schemas import (
    ConversationState,
    CreateRecord,
    LastAction,
    ListRecords,
    RecordStatus,
    RecordType,
    TargetRef,
    UpdateRecord,
)
from services import (
    create_record,
    get_conversation_state,
    get_or_create_conversation_state,
    list_records_for_period,
    restore_record,
    save_conversation_state,
    set_status,
    update_record,
)

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=MSK)
DAY = datetime(2026, 10, 29, 0, 0, tzinfo=MSK)  # четверг, через три дня


def at(hour: int, minute: int = 0, day: datetime = DAY) -> datetime:
    return day.replace(hour=hour, minute=minute)


def make(db: Session, user_id: UUID, **fields):
    fields.setdefault("type", RecordType.TASK)
    fields.setdefault("time_given", fields.get("start") is not None)
    result = create_record(db, user_id, CreateRecord(**fields), now=NOW)
    assert result.ok, result.error
    return result


def update(**fields) -> UpdateRecord:
    return UpdateRecord(target=TargetRef(), **fields)


# --- состояние разговора и миграция 0003 ----------------------------------------------------


def test_new_state_fields_saved_and_read(db: Session) -> None:
    user_id, conversation_id = uuid4(), uuid4()
    rec = make(db, user_id, title="Позвонить Ивану", start=at(10)).records[0]
    state = get_or_create_conversation_state(db, conversation_id, user_id)
    assert (state.shown, state.last_action, state.pending_skipped) == ([], None, False)

    state = state.model_copy(
        update={
            "shown": [rec.id],
            "last_action": LastAction(
                action="update_record", record_ids=[rec.id], before=[{"start": at(9).isoformat()}]
            ),
            "pending_skipped": True,
        }
    )
    save_conversation_state(db, state)
    db.expire_all()

    loaded = get_conversation_state(db, conversation_id, user_id)
    assert loaded.shown == [rec.id]
    assert loaded.last_action.record_ids == [rec.id]
    assert loaded.last_action.before == [{"start": at(9).isoformat()}]
    assert loaded.pending_skipped is True


# --- сервисы не коммитят ---------------------------------------------------------------------


def test_services_do_not_commit(engine: Engine) -> None:
    user_id = uuid4()
    with Session(engine) as session:
        make(session, user_id, title="Невидимая задача", start=at(10))
        with engine.connect() as other:  # другое соединение видит только закоммиченное
            seen = other.scalar(select(models.Record.id).where(models.Record.user_id == user_id))
        session.rollback()
    assert seen is None


# --- изменение записи ---------------------------------------------------------------------


def test_update_changes_only_given_fields_and_returns_before(db: Session) -> None:
    user_id = uuid4()
    rec = make(db, user_id, title="Отправить отчёт", start=at(15), deadline=at(18)).records[0]

    change = update_record(db, user_id, rec.id, update(start=at(16)), now=NOW)

    assert change.result.ok
    updated = change.result.records[0]
    assert updated.start == at(16)
    assert (updated.title, updated.deadline) == ("Отправить отчёт", at(18))  # не тронуты
    assert change.before == {"start": at(15).isoformat()}


def test_update_to_day_without_time_makes_all_day(db: Session) -> None:
    user_id = uuid4()
    rec = make(db, user_id, title="Купить хлеб", start=at(10)).records[0]

    change = update_record(db, user_id, rec.id, update(start=DAY, time_given=False), now=NOW)

    assert change.result.ok and change.result.records[0].all_day is True
    assert change.before == {"start": at(10).isoformat(), "time_given": True}


def test_update_rejects_past_and_foreign_record(db: Session) -> None:
    owner = uuid4()
    rec = make(db, owner, title="Отправить отчёт", start=at(15)).records[0]

    past = update_record(db, owner, rec.id, update(start=NOW - timedelta(days=1)), now=NOW)
    assert past.result.ok is False and "прошлом" in past.result.error
    assert past.before == {}

    foreign = update_record(db, uuid4(), rec.id, update(title="Чужое"), now=NOW)
    assert foreign.result.ok is False and foreign.result.error == "Запись не найдена."

    db.expire_all()
    assert db.get(models.Record, rec.id).start == at(15)  # ничего не поменялось


def test_moving_meeting_keeps_duration(db: Session) -> None:
    user_id = uuid4()
    rec = make(
        db, user_id, type=RecordType.MEETING, title="Планёрка", start=at(10), end=at(11)
    ).records[0]

    change = update_record(db, user_id, rec.id, update(start=at(14)), now=NOW)

    assert (change.result.records[0].start, change.result.records[0].end) == (at(14), at(15))
    assert change.before == {"start": at(10).isoformat(), "end": at(11).isoformat()}


# --- статус -------------------------------------------------------------------------------


def test_status_done_cancelled_active_and_list(db: Session) -> None:
    user_id = uuid4()
    rec = make(db, user_id, title="Позвонить Ивану", start=at(10)).records[0]
    period = ListRecords(date_from=DAY, date_to=DAY + timedelta(days=1))

    def listed() -> list[UUID]:
        return [r.id for r in list_records_for_period(db, user_id, period).records]

    done = set_status(db, user_id, rec.id, RecordStatus.DONE)
    assert done.result.records[0].status is RecordStatus.DONE
    assert done.before == {"status": "active"}

    cancelled = set_status(db, user_id, rec.id, RecordStatus.CANCELLED)
    assert cancelled.before == {"status": "done"}
    assert rec.id not in listed()  # отменённая пропала из списка

    back = set_status(db, user_id, rec.id, RecordStatus.ACTIVE)
    assert back.before == {"status": "cancelled"}
    assert rec.id in listed()  # и вернулась

    assert set_status(db, uuid4(), rec.id, RecordStatus.DONE).result.ok is False  # чужая


# --- откат существующими сервисами -----------------------------------------------------------


def test_undo_update(db: Session) -> None:
    user_id = uuid4()
    rec = make(db, user_id, title="Отправить отчёт", start=at(15)).records[0]
    change = update_record(db, user_id, rec.id, update(start=DAY, time_given=False), now=NOW)

    undo = restore_record(db, user_id, rec.id, change.before)

    restored = undo.result.records[0]
    assert (restored.start, restored.all_day) == (at(15), False)


def test_undo_clears_fields_that_were_empty(db: Session) -> None:
    """Поле было пустым — после «верни» снова пустое: срок, дата задачи, конец встречи."""
    user_id = uuid4()
    task = make(db, user_id, title="Купить молоко").records[0]  # без даты и срока
    meeting = make(db, user_id, type=RecordType.MEETING, title="Созвон", start=at(12)).records[0]

    dated = update_record(db, user_id, task.id, update(start=DAY, time_given=False), now=NOW)
    assert dated.result.records[0].all_day is True
    undo = restore_record(db, user_id, task.id, dated.before)
    assert undo.result.ok, undo.result.error
    restored = undo.result.records[0]
    assert (restored.start, restored.all_day) == (None, False)

    with_deadline = update_record(db, user_id, task.id, update(deadline=at(18)), now=NOW)
    assert with_deadline.before == {"deadline": None}
    undo = restore_record(db, user_id, task.id, with_deadline.before)
    assert undo.result.records[0].deadline is None

    with_end = update_record(db, user_id, meeting.id, update(end=at(13)), now=NOW)
    undo = restore_record(db, user_id, meeting.id, with_end.before)
    assert (undo.result.records[0].start, undo.result.records[0].end) == (at(12), None)


def test_undo_moved_meeting_restores_start_and_end(db: Session) -> None:
    user_id = uuid4()
    rec = make(
        db, user_id, type=RecordType.MEETING, title="Планёрка", start=at(15), end=at(16)
    ).records[0]
    moved = update_record(db, user_id, rec.id, update(start=at(17)), now=NOW)
    assert (moved.result.records[0].start, moved.result.records[0].end) == (at(17), at(18))

    undo = restore_record(db, user_id, rec.id, moved.before)

    assert (undo.result.records[0].start, undo.result.records[0].end) == (at(15), at(16))


def test_undo_status(db: Session) -> None:
    user_id = uuid4()
    rec = make(db, user_id, title="Позвонить Ивану", start=at(10)).records[0]
    change = set_status(db, user_id, rec.id, RecordStatus.DONE)

    undo = set_status(db, user_id, rec.id, RecordStatus(change.before["status"]))

    assert undo.result.records[0].status is RecordStatus.ACTIVE


def test_undo_create_is_cancel(db: Session) -> None:
    user_id = uuid4()
    rec = make(db, user_id, title="Купить билеты", start=at(10)).records[0]

    undo = set_status(db, user_id, rec.id, RecordStatus.CANCELLED)

    assert undo.result.ok
    period = ListRecords(date_from=DAY, date_to=DAY + timedelta(days=1))
    assert list_records_for_period(db, user_id, period).records == []


def test_undo_restores_past_time(db: Session) -> None:
    """Запись на 10:00 перенесли на 12:00, а «верни» сказали, когда 10:00 уже прошло:
    изменение на прошедшее время отклоняется, откат — нет."""
    user_id = uuid4()
    rec = make(db, user_id, title="Позвонить маме", start=at(10)).records[0]
    change = update_record(db, user_id, rec.id, update(start=at(12)), now=NOW)
    later = NOW + timedelta(days=4)  # время at(10) уже прошло

    refused = update_record(db, user_id, rec.id, update(start=at(10)), now=later)
    allowed = restore_record(db, user_id, rec.id, change.before)

    assert refused.result.ok is False
    assert allowed.result.ok and allowed.result.records[0].start == at(10)


def test_restore_rejects_foreign_record_and_unknown_fields(db: Session) -> None:
    owner = uuid4()
    rec = make(db, owner, title="Отправить отчёт", start=at(15)).records[0]

    assert restore_record(db, uuid4(), rec.id, {"start": None}).result.ok is False
    assert restore_record(db, owner, rec.id, {"status": "done"}).result.ok is False


def test_failed_save_does_not_break_turn(db: Session) -> None:
    """Ошибка базы при изменении — `ok=False`, а состояние разговора сохраняется дальше."""
    user_id, conversation_id = uuid4(), uuid4()
    rec = make(db, user_id, title="Отправить отчёт", start=at(15)).records[0]
    state = get_or_create_conversation_state(db, conversation_id, user_id)

    # Пустое название нарушает ограничение базы `title_not_empty`.
    broken = update_record(db, user_id, rec.id, update(title="   "), now=NOW)
    assert broken.result.ok is False

    save_conversation_state(db, state.model_copy(update={"shown": [rec.id]}))
    db.commit()
    db.expire_all()
    assert db.get(models.Record, rec.id).title == "Отправить отчёт"
    assert get_conversation_state(db, conversation_id, user_id).shown == [rec.id]


# --- конфликт и дубль -----------------------------------------------------------------------


def test_meeting_conflict_with_no_end_rule_on_create_and_move(db: Session) -> None:
    user_id = uuid4()
    alfa = make(db, user_id, type=RecordType.MEETING, title="Созвон с Альфой", start=at(12))
    alfa_id = alfa.records[0].id

    anna = create_record(
        db,
        user_id,
        CreateRecord(
            type=RecordType.MEETING, title="Встреча с Анной", start=at(12, 30), time_given=True
        ),
        now=NOW,
    )
    assert anna.ok  # создана
    assert [c.id for c in anna.conflicts] == [alfa_id]  # без конца — 60 минут

    later = make(db, user_id, type=RecordType.MEETING, title="Демо", start=at(14))
    assert later.conflicts == []
    moved = update_record(db, user_id, later.records[0].id, update(start=at(12, 45)), now=NOW)
    assert {c.id for c in moved.result.conflicts} == {alfa_id, anna.records[0].id}

    task = make(db, user_id, title="Задача в то же время", start=at(12))
    assert task.conflicts == []  # пересечения — только у встреч


def test_exact_duplicate_not_created(db: Session) -> None:
    user_id = uuid4()
    first = make(db, user_id, type=RecordType.MEETING, title="Созвон с Альфой", start=at(12))

    again = create_record(
        db,
        user_id,
        CreateRecord(
            type=RecordType.MEETING, title="созвон с альфой", start=at(12), time_given=True
        ),
        now=NOW,
    )

    assert again.ok is False and again.error
    assert [r.id for r in again.records] == [first.records[0].id]
    count = db.scalar(text("select count(*) from records where user_id = :u"), {"u": user_id})
    assert count == 1


# --- список без конца периода -----------------------------------------------------------------


def test_list_without_date_to(db: Session) -> None:
    user_id = uuid4()
    soon = make(db, user_id, title="Завтра", start=at(10, day=DAY - timedelta(days=2)))
    far = make(db, user_id, title="Через месяц", start=at(10) + timedelta(days=30))
    undated = make(db, user_id, title="Прочитать книгу")
    gone = make(db, user_id, title="Отменённая", start=at(11))
    set_status(db, user_id, gone.records[0].id, RecordStatus.CANCELLED)

    result = list_records_for_period(
        db, user_id, ListRecords(date_from=NOW.replace(hour=0), date_to=None)
    )

    titles = [r.title for r in result.records]
    assert titles == ["Завтра", "Через месяц", "Прочитать книгу"]
    assert soon and far and undated


# --- один коммит на реплику -------------------------------------------------------------------


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_chat_rolls_back_whole_turn(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Запись изменена, сохранение состояния упало — ни запись, ни состояние не меняются."""
    user_id, conversation_id = uuid4(), uuid4()
    rec = make(db, user_id, title="Отправить отчёт", start=at(15)).records[0]
    get_or_create_conversation_state(db, conversation_id, user_id)
    db.commit()  # подготовка сохранена; дальше — только то, что сделает реплика

    async def turn(session, uid, cid, text_, timezone_name, llm_config=None):
        change = update_record(session, uid, rec.id, update(start=at(16)), now=NOW)
        assert change.result.ok
        broken = ConversationState(
            conversation_id=cid,
            user_id=uid,
            shown=[rec.id],
            awaiting="choice",
            last_action=LastAction(action="update_record", record_ids=[rec.id]),
        )
        save_conversation_state(session, broken)
        raise RuntimeError("сохранение состояния упало")

    monkeypatch.setattr("api.chat.process_user_turn", turn)
    app.dependency_overrides[get_session] = lambda: db
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat",
                headers={"X-User-Id": str(user_id)},
                json={
                    "conversation_id": str(conversation_id),
                    "text": "перенеси на 16",
                    "timezone": "Europe/Moscow",
                },
            )
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 500
    db.expire_all()
    assert db.get(models.Record, rec.id).start == at(15)
    state = get_conversation_state(db, conversation_id, user_id)
    assert (state.shown, state.awaiting, state.last_action) == ([], None, None)
