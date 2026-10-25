"""Смоук-тест хранилища (backend-01a): запись создаётся, читается и видна только владельцу."""

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from db import models
from schemas import Record, RecordStatus, RecordType

MSK = ZoneInfo("Europe/Moscow")


def test_create_and_read_record(db: Session) -> None:
    owner, stranger = uuid4(), uuid4()
    start = datetime(2026, 10, 29, 11, 0, tzinfo=MSK)

    db.add(
        models.Record(
            user_id=owner,
            type=RecordType.MEETING,
            title="Встреча с дизайнером",
            start=start,
            end=start + timedelta(hours=1),
        )
    )
    db.add(models.Record(user_id=stranger, type=RecordType.TASK, title="Чужая задача"))
    db.flush()

    rows = db.scalars(select(models.Record).where(models.Record.user_id == owner)).all()

    # Изоляция: пользователь видит только свои записи.
    assert len(rows) == 1
    # Наружу запись уходит Pydantic-схемой из контракта.
    record = Record.model_validate(rows[0])
    assert record.title == "Встреча с дизайнером"
    assert record.type is RecordType.MEETING
    assert record.status is RecordStatus.ACTIVE
    assert record.all_day is False
    # Время вернулось тем же моментом и с часовым поясом (Postgres хранит его в UTC).
    assert record.start == start
    assert record.start.utcoffset() is not None
    assert record.created_at.utcoffset() is not None


def test_naive_datetime_is_rejected(db: Session) -> None:
    db.add(
        models.Record(
            user_id=uuid4(),
            type=RecordType.REMINDER,
            title="Позвонить Ивану",
            start=datetime(2026, 10, 26, 10, 0),  # без часового пояса
        )
    )
    with pytest.raises(StatementError, match="без часового пояса"):
        db.flush()
