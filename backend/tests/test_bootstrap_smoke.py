"""Смоук-тест импорта датасета (backend-01b): 5 строк из фикстуры CSV."""

from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import models
from schemas import Record, RecordStatus, RecordType
from services.bootstrap import bootstrap_user_data

FIXTURE = Path(__file__).parent / "fixtures" / "events_5.csv"
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))


def test_bootstrap_loads_fixture_once(db: Session) -> None:
    user_id = uuid4()

    loaded = bootstrap_user_data(db, user_id, "Asia/Yekaterinburg", csv_path=FIXTURE, now=NOW)
    assert loaded == 5

    rows = db.scalars(
        select(models.Record).where(models.Record.user_id == user_id).order_by(models.Record.start)
    ).all()
    records = {r.title: Record.model_validate(r) for r in rows}
    assert len(records) == 5

    # Время из CSV — локальное время пользователя: 13:45 так и осталось 13:45 по Екатеринбургу.
    meeting = records["Встреча с Иваном по CRM"]
    assert meeting.start.astimezone(ZoneInfo("Asia/Yekaterinburg")).strftime("%H:%M") == "13:45"
    assert meeting.start.utcoffset() is not None

    # Типы по тексту.
    assert meeting.type is RecordType.MEETING
    assert records["Отправить итоги встречи Марией"].type is RecordType.TASK
    assert records["Провести планёрку по сайту"].type is RecordType.MEETING
    assert records["Напомнить Анной про договору"].type is RecordType.REMINDER
    assert records["Позвонить Сергею"].type is RecordType.TASK

    # Статус: прошлое → done, будущее → active.
    assert meeting.status is RecordStatus.DONE
    assert records["Отправить итоги встречи Марией"].status is RecordStatus.DONE
    assert records["Провести планёрку по сайту"].status is RecordStatus.ACTIVE

    # Идемпотентность: второй вызов ничего не добавляет.
    assert bootstrap_user_data(db, user_id, "Asia/Yekaterinburg", csv_path=FIXTURE, now=NOW) == 0
    count = db.scalars(select(models.Record.id).where(models.Record.user_id == user_id)).all()
    assert len(count) == 5
