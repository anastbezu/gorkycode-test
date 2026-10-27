"""Диалоги изменения записей на тестовой PostgreSQL (agent-07, agent-09).

Модель — сценарий (подменённый `get_action`), всё остальное настоящее: `process_user_turn`,
поиск цели, сервисы записей и состояние разговора. Без базы тесты пропускаются.
"""

import asyncio
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from agent import agent as agent_module
from agent import targets as targets_module
from agent.agent import process_user_turn
from db import models
from schemas import (
    CreateRecord,
    Record,
    RecordStatus,
    RecordType,
    SearchFilters,
    SetStatus,
    TargetMatch,
    TargetRef,
    UndoLast,
    UpdateRecord,
)
from services import get_conversation_state

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 21, 10, 0, tzinfo=MSK)  # среда, как в test-cases.md


def at(day, hour=0, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=MSK)


class Dialog:
    """Один разговор: реплики уходят в `process_user_turn`, модель отвечает сценарием."""

    def __init__(self, db: Session, monkeypatch):
        self.db, self.user_id, self.conversation_id = db, uuid4(), uuid4()
        self.actions: list = []

        async def model(*args, **kwargs):
            return self.actions.pop(0)

        monkeypatch.setattr(agent_module, "get_action", model)

    def add(self, title, start, *, type=RecordType.MEETING):
        row = models.Record(user_id=self.user_id, type=type, title=title, start=start,
                            all_day=False)
        self.db.add(row)
        self.db.flush()
        return row

    def say(self, text, *actions):
        self.actions.extend(actions)
        return asyncio.run(process_user_turn(
            self.db, self.user_id, self.conversation_id, text, "Europe/Moscow", now=NOW,
        ))

    def state(self):
        return get_conversation_state(self.db, self.conversation_id, self.user_id)

    def row(self, row):
        self.db.refresh(row)
        return row


def cancel(**target):
    return SetStatus(target=TargetRef(**target), status=RecordStatus.CANCELLED)


@pytest.fixture
def dialog(db: Session, monkeypatch):
    return Dialog(db, monkeypatch)


def test_move_by_text_then_undo_then_nothing_to_undo(dialog) -> None:
    meeting = dialog.add("Встреча с Иваном", at(22, 15))
    move = UpdateRecord(target=TargetRef(text="встречу с Иваном"), start=at(23, 15),
                        time_given=True)

    reply = dialog.say("Перенеси встречу с Иваном на пятницу", move).reply
    assert dialog.row(meeting).start == at(23, 15)
    assert "Встреча с Иваном" in reply and "23.10 в 15:00" in reply
    last = dialog.state().last_action
    assert last.action == "update_record" and last.record_ids == [meeting.id]
    assert datetime.fromisoformat(last.before[0]["start"]) == at(22, 15)

    reply = dialog.say("Верни", UndoLast()).reply
    assert dialog.row(meeting).start == at(22, 15)
    assert reply.startswith("Вернул как было")
    assert dialog.state().last_action is None
    assert dialog.say("Верни", UndoLast()).reply == "Нечего возвращать."


def test_cancel_is_immediate_and_offers_undo(dialog) -> None:
    meeting = dialog.add("Встреча с дизайнером", at(22, 11))
    reply = dialog.say("Отмени встречу с дизайнером", cancel(text="встречу с дизайнером")).reply
    assert dialog.row(meeting).status == RecordStatus.CANCELLED
    assert "Отменил" in reply and "22.10 в 11:00" in reply and "верни" in reply

    dialog.say("Верни", UndoLast())
    assert dialog.row(meeting).status == RecordStatus.ACTIVE


def test_ambiguous_target_changes_nothing_until_choice(dialog) -> None:
    first = dialog.add("Встреча с Иваном", at(22, 15))
    second = dialog.add("Встреча с Иваном", at(27, 8, 45))
    move = UpdateRecord(target=TargetRef(text="встречу с Иваном"), start=at(30, 15),
                        time_given=True)

    response = dialog.say("Перенеси встречу с Иваном на пятницу", move)
    assert response.awaiting == "choice"
    assert "1) «Встреча с Иваном» на 22.10 в 15:00" in response.reply
    assert "2) «Встреча с Иваном» на 27.10 в 08:45" in response.reply
    assert dialog.row(first).start == at(22, 15) and dialog.row(second).start == at(27, 8, 45)
    state = dialog.state()
    assert state.shown == [first.id, second.id] == state.candidates

    chosen = UpdateRecord(target=TargetRef(index=2), start=at(30, 8, 45), time_given=True)
    response = dialog.say("вторую", chosen)
    assert response.awaiting is None
    assert dialog.row(second).start == at(30, 8, 45)
    assert dialog.row(first).start == at(22, 15)
    state = dialog.state()
    assert state.pending is None and state.candidates == []


def test_similar_only_asks_and_executes_after_yes(dialog, monkeypatch) -> None:
    other = dialog.add("Созвон с Севером по новому продукту", at(22, 12))
    monkeypatch.setattr(targets_module, "find_target", lambda *args: TargetMatch(
        similar=[Record.model_validate(other)]))

    response = dialog.say("Отмени созвон с Севером по CRM", cancel(text="созвон с Севером по CRM"))
    assert response.reply.startswith("Точно такой нет. Может, «Созвон с Севером")
    assert response.awaiting == "choice"
    assert dialog.row(other).status == RecordStatus.ACTIVE  # похожая без ответа не меняется

    dialog.say("Да", cancel(index=1))
    assert dialog.row(other).status == RecordStatus.CANCELLED


def test_mass_cancel_asks_then_cancels_all_and_undo_restores_all(dialog) -> None:
    calls = [dialog.add(f"Созвон {n}", at(22, 10 + n)) for n in range(3)]
    dialog.add("Обед", at(22, 13))
    mass = cancel(all=True, text="созвон", filters=SearchFilters(
        types=[RecordType.MEETING], date_from=at(19), date_to=at(26)))

    response = dialog.say("Отмени все созвоны на этой неделе", mass)
    assert response.reply.startswith("Отменить 3 записи: 1) «Созвон 0»")
    assert all(dialog.row(c).status == RecordStatus.ACTIVE for c in calls)

    response = dialog.say("Да", cancel(all=True))
    assert all(dialog.row(c).status == RecordStatus.CANCELLED for c in calls)
    assert dialog.state().last_action.record_ids == [c.id for c in calls]

    dialog.say("Верни", UndoLast())
    assert all(dialog.row(c).status == RecordStatus.ACTIVE for c in calls)


def test_replaces_last_returns_first_and_changes_second(dialog) -> None:
    integration = dialog.add("Созвон с Вектором по интеграции", at(22, 12))
    site = dialog.add("Созвон с Вектором по сайту", at(23, 12))

    dialog.say("Отмени созвон с Вектором", cancel(text="созвон с Вектором по интеграции"))
    assert dialog.row(integration).status == RecordStatus.CANCELLED

    fix = SetStatus(target=TargetRef(text="созвон по сайту"), status=RecordStatus.CANCELLED,
                    replaces_last=True)
    reply = dialog.say("Нет, не этот, а тот, что по сайту", fix).reply
    assert dialog.row(integration).status == RecordStatus.ACTIVE
    assert dialog.row(site).status == RecordStatus.CANCELLED
    assert reply.startswith("Вернул «Созвон с Вектором по интеграции»")
    assert "Отменил: «Созвон с Вектором по сайту»" in reply
    assert dialog.state().last_action.record_ids == [site.id]


def test_correction_right_after_create_uses_focus(dialog) -> None:
    create = CreateRecord(type="meeting", title="встреча с Максимом", start=at(22, 15),
                          time_given=True)
    dialog.say("Поставь встречу с Максимом завтра в 15", create)
    fix = UpdateRecord(target=TargetRef(focus=True), start=at(22, 16), time_given=True)
    reply = dialog.say("Нет, не в 15, а в 16", fix).reply
    assert "22.10 в 16:00" in reply
    [row] = dialog.db.query(models.Record).filter_by(user_id=dialog.user_id).all()
    assert row.start == at(22, 16)


def test_undo_create_cancels_created_record(dialog) -> None:
    create = CreateRecord(type="task", title="купить хлеб", time_given=False)
    dialog.say("Запиши купить хлеб", create)
    dialog.say("Верни", UndoLast())
    [row] = dialog.db.query(models.Record).filter_by(user_id=dialog.user_id).all()
    assert row.status == RecordStatus.CANCELLED


def test_unknown_number_and_not_found(dialog) -> None:
    reply = dialog.say("Перенеси пятую на завтра",
                       UpdateRecord(target=TargetRef(index=5), start=at(22, 9))).reply
    assert reply == "В показанном списке нет записи № 5."
    assert dialog.say("Отмени встречу с дизайнером",
                      cancel(text="встречу с дизайнером")).reply == (
        "Не нашёл «встречу с дизайнером».")


# --- Как отвечала модель в живом прогоне 27.10.2026 (раздел 7) -----------------------------

def test_move_to_day_keeps_previous_time(dialog) -> None:
    """7.1: «на пятницу» модель присылает полночь без time_given — время прежнее."""
    meeting = dialog.add("Встреча с Иваном", at(22, 15))
    move = UpdateRecord(target=TargetRef(text="встречу с Иваном"), start=at(23))
    reply = dialog.say("Перенеси встречу с Иваном на пятницу", move).reply
    assert dialog.row(meeting).start == at(23, 15)
    assert dialog.row(meeting).all_day is False
    assert "23.10 в 15:00" in reply


def test_replaces_last_keeps_status_of_previous_action(dialog) -> None:
    """7.15: модель вернула status=active и «по сайту» — отменяется созвон по сайту."""
    integration = dialog.add("Созвон с Вектором по интеграции", at(22, 15))
    site = dialog.add("Созвон с Вектором по сайту", at(28, 12))
    dialog.say("Отмени созвон с Вектором по интеграции",
               cancel(text="созвон с Вектором по интеграции"))
    wrong = SetStatus(target=TargetRef(text="по сайту"), status=RecordStatus.ACTIVE,
                      replaces_last=True)
    response = dialog.say("Нет, не этот, а тот, что по сайту", wrong)
    assert dialog.row(integration).status == RecordStatus.ACTIVE
    assert dialog.row(site).status == RecordStatus.CANCELLED
    assert response.result.ok


def test_shift_by_description_asks_model_again_with_record_in_focus(dialog) -> None:
    """7.17: «на час позже» по описанию — модель не видела время; второй вызов с фокусом."""
    meeting = dialog.add("Встреча с Натальей по презентации", at(27, 16, 30))
    blind = UpdateRecord(target=TargetRef(focus=True, text="встречу с Натальей"))
    seen = UpdateRecord(target=TargetRef(focus=True), start=at(27, 17, 30), time_given=True)
    reply = dialog.say("Перенеси встречу с Натальей на час позже", blind, seen).reply
    assert dialog.row(meeting).start == at(27, 17, 30)
    assert "27.10 в 17:30" in reply

    dialog.say("Верни как было", UndoLast())  # 7.18
    assert dialog.row(meeting).start == at(27, 16, 30)


def test_shift_without_answer_on_retry_asks_user(dialog) -> None:
    meeting = dialog.add("Встреча с Натальей по презентации", at(27, 16, 30))
    blind = UpdateRecord(target=TargetRef(text="встречу с Натальей"))
    reply = dialog.say("Перенеси встречу с Натальей", blind, blind).reply
    assert reply.startswith("Что изменить")
    assert dialog.row(meeting).start == at(27, 16, 30)


def test_yes_with_repeated_description_takes_asked_records(dialog) -> None:
    """7.20: на «Да» модель повторила фильтры — отменяется то, что спросили, без нового вопроса."""
    rows = [dialog.add(f"Созвон {n}", at(22, 10 + n)) for n in range(3)]
    tomorrow = SearchFilters(date_from=at(22), date_to=at(23))
    dialog.say("Отмени всё на завтра", cancel(all=True, filters=tomorrow))
    response = dialog.say("Да", cancel(all=True, filters=tomorrow))
    assert response.awaiting is None and response.result.ok
    assert all(dialog.row(r).status == RecordStatus.CANCELLED for r in rows)
