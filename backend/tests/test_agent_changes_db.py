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
    assert "Встреча с Иваном" in reply and "послезавтра, 23 октября, в 15:00" in reply
    last = dialog.state().last_action
    assert last.action == "update_record" and last.record_ids == [meeting.id]
    assert datetime.fromisoformat(last.before[0]["start"]) == at(22, 15)

    reply = dialog.say("Верни", UndoLast()).reply
    assert dialog.row(meeting).start == at(22, 15)
    assert reply == "Вернул «Встреча с Иваном» — завтра, 22 октября, в 15:00."
    assert dialog.state().last_action is None
    assert dialog.say("Верни", UndoLast()).reply == "Нечего возвращать."


def test_cancel_is_immediate_and_offers_undo(dialog) -> None:
    meeting = dialog.add("Встреча с дизайнером", at(22, 11))
    reply = dialog.say("Отмени встречу с дизайнером", cancel(text="встречу с дизайнером")).reply
    assert dialog.row(meeting).status == RecordStatus.CANCELLED
    assert "Отменил" in reply and "завтра, 22 октября, в 11:00" in reply and "верни" in reply

    dialog.say("Верни", UndoLast())
    assert dialog.row(meeting).status == RecordStatus.ACTIVE


def test_ambiguous_target_changes_nothing_until_choice(dialog) -> None:
    first = dialog.add("Встреча с Иваном", at(22, 15))
    second = dialog.add("Встреча с Иваном", at(27, 8, 45))
    move = UpdateRecord(target=TargetRef(text="встречу с Иваном"), start=at(30, 15),
                        time_given=True)

    response = dialog.say("Перенеси встречу с Иваном на пятницу", move)
    assert response.awaiting == "choice"
    # Номера — на экране (candidates), текст их не повторяет (assistant-texts 7).
    assert response.reply == "Нашёл 2 встречи. Какую именно?"
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
    # Команда на неделю — у записей называется день (assistant-texts 7, пример 7.22).
    assert response.reply == ("Нашёл 3 встречи: завтра в 10:00 — созвон 0; завтра в 11:00 — "
                              "созвон 1; завтра в 12:00 — созвон 2. Отменить все?")
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
    assert "Отменил «Созвон с Вектором по сайту»" in reply
    assert dialog.state().last_action.record_ids == [site.id]


def test_correction_right_after_create_uses_focus(dialog) -> None:
    create = CreateRecord(type="meeting", title="встреча с Максимом", start=at(22, 15),
                          time_given=True)
    dialog.say("Поставь встречу с Максимом завтра в 15", create)
    fix = UpdateRecord(target=TargetRef(focus=True), start=at(22, 16), time_given=True)
    reply = dialog.say("Нет, не в 15, а в 16", fix).reply
    assert "завтра, 22 октября, в 16:00" in reply
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
    assert "послезавтра, 23 октября, в 15:00" in reply


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


def test_yes_with_repeated_description_takes_asked_records(dialog) -> None:
    """7.20: на «Да» модель повторила фильтры — отменяется то, что спросили, без нового вопроса."""
    rows = [dialog.add(f"Созвон {n}", at(22, 10 + n)) for n in range(3)]
    tomorrow = SearchFilters(date_from=at(22), date_to=at(23))
    dialog.say("Отмени всё на завтра", cancel(all=True, filters=tomorrow))
    response = dialog.say("Да", cancel(all=True, filters=tomorrow))
    assert response.awaiting is None and response.result.ok
    assert all(dialog.row(r).status == RecordStatus.CANCELLED for r in rows)


# --- Ревью PR agent-07: регрессии -----------------------------------------------------------

def test_new_mass_request_during_choice_is_not_taken_as_confirmation(dialog) -> None:
    """«Отметь отчёт выполненным» → выбор → «Отмени все созвоны»: отчёты не трогаем."""
    reports = [dialog.add(f"Подготовить отчёт {n}", at(23, 10 + n), type=RecordType.TASK)
               for n in range(2)]
    calls = [dialog.add(f"Созвон {n}", at(22, 10 + n)) for n in range(2)]
    response = dialog.say("Отметь отчёт выполненным",
                          SetStatus(target=TargetRef(text="отчёт"), status=RecordStatus.DONE))
    assert response.awaiting == "choice"

    response = dialog.say("Отмени все созвоны", cancel(all=True, text="созвоны"))
    # Новый массовый запрос: своё подтверждение по созвонам, ничего не изменено.
    assert response.awaiting == "confirm"
    assert dialog.state().candidates == [c.id for c in calls]
    assert all(dialog.row(r).status == RecordStatus.ACTIVE for r in reports + calls)

    dialog.say("Да", cancel(all=True))
    assert all(dialog.row(c).status == RecordStatus.CANCELLED for c in calls)
    assert all(dialog.row(r).status == RecordStatus.ACTIVE for r in reports)


def test_yes_to_other_mass_question_with_other_status_is_new_request(dialog) -> None:
    calls = [dialog.add(f"Созвон {n}", at(22, 10 + n)) for n in range(2)]
    dialog.say("Отмени все созвоны", cancel(all=True, text="созвоны"))
    done_all = SetStatus(target=TargetRef(all=True, text="созвоны"), status=RecordStatus.DONE)
    response = dialog.say("Нет, отметь все созвоны выполненными", done_all)
    assert response.awaiting == "confirm"  # новое подтверждение, а не отмена по старому
    assert all(dialog.row(c).status == RecordStatus.ACTIVE for c in calls)


def test_mass_change_is_all_or_nothing(dialog, monkeypatch) -> None:
    """Сервис упал на второй записи — первая возвращается, last_action прежний."""
    from agent import changes as changes_module

    calls = [dialog.add(f"Созвон {n}", at(22, 10 + n)) for n in range(3)]
    dialog.say("Отмени все созвоны", cancel(all=True, text="созвоны"))
    real = changes_module.set_status
    seen = []

    def flaky(db, user_id, record_id, status):
        seen.append(record_id)
        if len(seen) == 2:
            from schemas import ActionResult
            from services.records import RecordChange
            return RecordChange(ActionResult(action="set_status", ok=False,
                                             error="Не удалось изменить статус."))
        return real(db, user_id, record_id, status)

    monkeypatch.setattr(changes_module, "set_status", flaky)
    response = dialog.say("Да", cancel(all=True))
    assert not response.result.ok
    assert all(dialog.row(c).status == RecordStatus.ACTIVE for c in calls)
    assert dialog.state().last_action is None


def test_corrected_status_reaches_reply_and_pending(dialog) -> None:
    """replaces_last с ошибочным active: ответ и черновик — с исправленным cancelled."""
    integration = dialog.add("Созвон с Вектором по интеграции", at(22, 15))
    site = dialog.add("Созвон с Вектором по сайту", at(28, 12))
    dialog.add("Встреча по сайту", at(29, 12))
    dialog.say("Отмени созвон с Вектором по интеграции",
               cancel(text="созвон с Вектором по интеграции"))

    wrong = SetStatus(target=TargetRef(text="сайт"), status=RecordStatus.ACTIVE,
                      replaces_last=True)
    response = dialog.say("Нет, не этот, а тот, что по сайту", wrong)
    assert response.awaiting == "choice"  # «по сайту» — две записи
    assert dialog.state().pending.root.status == RecordStatus.CANCELLED
    assert dialog.row(integration).status == RecordStatus.ACTIVE

    response = dialog.say("Первую", SetStatus(target=TargetRef(index=1),
                                              status=RecordStatus.CANCELLED))
    assert dialog.row(site).status == RecordStatus.CANCELLED
    assert "Отменил" in response.reply and "Вернул в активные" not in response.reply


def test_corrected_status_reply_when_target_is_single(dialog) -> None:
    dialog.add("Созвон с Вектором по интеграции", at(22, 15))
    dialog.add("Созвон с Вектором по сайту", at(28, 12))
    dialog.say("Отмени созвон с Вектором по интеграции",
               cancel(text="созвон с Вектором по интеграции"))
    wrong = SetStatus(target=TargetRef(text="по сайту"), status=RecordStatus.ACTIVE,
                      replaces_last=True)
    reply = dialog.say("Нет, не этот, а тот, что по сайту", wrong).reply
    assert "Отменил «Созвон с Вектором по сайту»" in reply
    assert "в активные" not in reply


def test_shift_by_description_is_counted_by_code(dialog) -> None:
    """7.17, 7.18: «на час позже» — модель шлёт только сдвиг, время считает код (один вызов)."""
    meeting = dialog.add("Встреча с Натальей по презентации", at(27, 16, 30))
    later = UpdateRecord(target=TargetRef(text="встречу с Натальей"), shift_minutes=60)
    reply = dialog.say("Перенеси встречу с Натальей на час позже", later).reply
    assert dialog.row(meeting).start == at(27, 17, 30)
    assert "во вторник, 27 октября, в 17:30" in reply

    dialog.say("Верни как было", UndoLast())
    assert dialog.row(meeting).start == at(27, 16, 30)


def test_shift_keeps_meeting_duration_and_moves_deadline(dialog) -> None:
    meeting = models.Record(user_id=dialog.user_id, type=RecordType.MEETING, title="Планёрка",
                            start=at(22, 10), end=at(22, 11), all_day=False)
    task = models.Record(user_id=dialog.user_id, type=RecordType.TASK, title="Сдать отчёт",
                         deadline=at(23, 18), all_day=False)
    dialog.db.add_all([meeting, task])
    dialog.db.flush()
    dialog.say("Сдвинь планёрку на полчаса раньше",
               UpdateRecord(target=TargetRef(text="планёрку"), shift_minutes=-30))
    assert (dialog.row(meeting).start, dialog.row(meeting).end) == (at(22, 9, 30), at(22, 10, 30))
    dialog.say("Сдвинь срок отчёта на день",
               UpdateRecord(target=TargetRef(text="отчёт"), shift_minutes=1440))
    assert dialog.row(task).deadline == at(24, 18)


def test_update_without_changes_asks_what_to_change(dialog) -> None:
    meeting = dialog.add("Встреча с Натальей", at(27, 16, 30))
    reply = dialog.say("Перенеси встречу с Натальей",
                       UpdateRecord(target=TargetRef(text="встречу с Натальей"))).reply
    assert reply.startswith("Что изменить")
    assert dialog.row(meeting).start == at(27, 16, 30)


def test_replaces_last_with_shift_keeps_restored(dialog) -> None:
    """«Нет, не эту, а с Натальей» со сдвигом: откат прошлого — в результате и ответе."""
    ivan = dialog.add("Встреча с Иваном", at(22, 15))
    natalia = dialog.add("Встреча с Натальей", at(27, 16, 30))
    dialog.say("Перенеси встречу с Иваном на час позже",
               UpdateRecord(target=TargetRef(text="встречу с Иваном"), shift_minutes=60))
    assert dialog.row(ivan).start == at(22, 16)
    fix = UpdateRecord(target=TargetRef(text="встречу с Натальей"), shift_minutes=60,
                       replaces_last=True)
    response = dialog.say("Нет, не эту, а с Натальей", fix)
    assert dialog.row(ivan).start == at(22, 15)
    assert dialog.row(natalia).start == at(27, 17, 30)
    assert [r.id for r in response.result.restored] == [ivan.id]
    assert response.reply.startswith("Вернул «Встреча с Иваном»")
