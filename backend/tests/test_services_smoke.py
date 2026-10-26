"""Смоук-тесты сервисного слоя (backend-02a) — чистые функции, база не нужна."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from schemas import ConversationState, CreateRecord, ListRecords, LLMAction, Record, RecordType
from services import create_record, merge_pending
from services import records as records_service
from services.records import _is_all_day, validate_create

MSK = ZoneInfo("Europe/Moscow")


class _NoDB:
    """Подставляется вместо сессии: тест упадёт, если сервис полезет в базу."""

    def __getattr__(self, name):
        raise AssertionError(f"обращение к базе ({name}) до проверки бизнес-правил")


def test_merge_pending_keeps_title_and_adds_start() -> None:
    draft = LLMAction(
        CreateRecord(type=RecordType.MEETING, title="встреча с Иваном", time_given=False)
    )
    state = ConversationState(
        conversation_id=uuid4(),
        user_id=uuid4(),
        pending=draft,
        missing=["start"],
        awaiting="answer",
    )
    start = datetime(2026, 10, 26, 14, 0, tzinfo=MSK)

    # Второй шаг: пользователь назвал только время; title во входящих аргументах пустой.
    merged = merge_pending(state, {"title": None, "start": start, "time_given": True})

    assert merged.pending.root.title == "встреча с Иваном"  # не затёрт
    assert merged.pending.root.start == start  # добавлен
    assert merged.pending.root.time_given is True
    assert merged.missing == []  # start больше не нужен


def test_create_record_rejects_end_before_start() -> None:
    now = datetime(2026, 10, 25, 12, 0, tzinfo=MSK)
    start = now + timedelta(days=1)
    action = CreateRecord(
        type=RecordType.MEETING,
        title="Встреча с дизайнером",
        start=start,
        end=start - timedelta(hours=1),
        time_given=True,
    )

    result = create_record(_NoDB(), uuid4(), action, now=now)

    assert result.ok is False
    assert result.action == "create_record"
    assert "окончания" in result.error
    assert result.records == []


def test_past_check_has_grace_for_timed_records() -> None:
    now = datetime(2026, 10, 25, 12, 0, tzinfo=MSK)

    def reminder(start: datetime) -> CreateRecord:
        return CreateRecord(
            type=RecordType.REMINDER, title="Позвонить Ивану", start=start, time_given=True
        )

    # LLM посчитала время до ответа модели — секунды «в прошлом» не ошибка.
    assert validate_create(reminder(now - timedelta(seconds=30)), now) is None
    rejected = validate_create(reminder(now - timedelta(minutes=2)), now)
    assert rejected is not None and rejected.ok is False


def test_all_day_only_when_day_named() -> None:
    now = datetime(2026, 10, 25, 20, 0, tzinfo=MSK)
    today = datetime(2026, 10, 25, 0, 0, tzinfo=MSK)

    named_day = CreateRecord(
        type=RecordType.TASK, title="Купить хлеб", start=today, time_given=False
    )
    no_date = CreateRecord(type=RecordType.TASK, title="Прочитать книгу", time_given=False)

    # «Сегодня» без времени вечером — не прошлое, запись на весь день.
    assert validate_create(named_day, now) is None
    assert _is_all_day(named_day) is True
    assert _is_all_day(no_date) is False


def test_list_without_end_accepts_none_and_appends_undated(monkeypatch):
    user_id = uuid4()
    now = datetime(2030, 1, 1, tzinfo=MSK)
    record = Record(id=uuid4(), user_id=user_id, type="task", title="Без срока", created_at=now)
    db = SimpleNamespace(scalars=lambda query: SimpleNamespace(all=lambda: []))
    calls = []

    def undated(session, owner, types):
        calls.append((session, owner, types))
        return [record]

    monkeypatch.setattr(records_service, "list_undated_records", undated)
    result = records_service.list_records_for_period(
        db, user_id, ListRecords(date_from=now, types=[RecordType.TASK]),
    )
    assert result.records == [record]
    assert calls == [(db, user_id, [RecordType.TASK])]
