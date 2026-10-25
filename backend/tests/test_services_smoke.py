"""Смоук-тесты сервисного слоя (backend-02a) — чистые функции, база не нужна."""

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from schemas import ConversationState, CreateRecord, LLMAction, RecordType
from services import create_record, merge_pending

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
