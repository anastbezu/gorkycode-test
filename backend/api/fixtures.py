"""Фиксированные данные для заглушек API (пока нет БД и агента)."""

from datetime import datetime, time, timedelta, timezone
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from schemas import Record, RecordStatus, RecordType

DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
_NS = UUID("6f1c0e2a-0000-4000-8000-000000000000")


def user_tz(name: str | None) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(name) if name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _at(tz, days: int, hour: int, minute: int = 0) -> datetime:
    day = datetime.now(tz).date() + timedelta(days=days)
    return datetime.combine(day, time(hour, minute), tzinfo=tz)


def demo_records(user_id: UUID = DEMO_USER_ID, tz_name: str | None = None) -> list[Record]:
    """Несколько записей «на сегодня и ближайшие дни» относительно текущего времени."""
    tz = user_tz(tz_name)
    created = datetime.now(timezone.utc) - timedelta(days=1)

    def rec(key: str, **fields) -> Record:
        return Record(id=uuid5(_NS, key), user_id=user_id, created_at=created, **fields)

    return [
        rec("call-ivan", type=RecordType.REMINDER, title="Позвонить Ивану",
            start=_at(tz, 1, 10)),
        rec("designer", type=RecordType.MEETING, title="Встреча с дизайнером",
            start=_at(tz, 0, 15), end=_at(tz, 0, 16)),
        rec("team", type=RecordType.MEETING, title="Планёрка с командой",
            start=_at(tz, 2, 11), end=_at(tz, 2, 12)),
        rec("report", type=RecordType.TASK, title="Отправить отчёт",
            deadline=_at(tz, 3, 23, 59)),
        rec("tickets", type=RecordType.TASK, title="Купить билеты"),
        rec("contract", type=RecordType.TASK, title="Отправить договор Ивану",
            start=_at(tz, -30, 12), status=RecordStatus.DONE),
    ]
