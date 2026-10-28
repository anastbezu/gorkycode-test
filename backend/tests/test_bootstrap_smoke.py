"""Импорт датасета (backend-01b): смоук-тест на 5 строк фикстуры, полный CSV, блокировка.

С backend-04 датасет загружается только демо-учёткам (`services/demo_accounts.py`, тесты —
`test_backend04.py`); гостю и новой учётке — нет (`test_api_routes.py`).
"""

import csv
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from db import models
from schemas import Record, RecordStatus, RecordType
from services.bootstrap import DATASET_PATH, bootstrap_user_data

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


def _count(db: Session, user_id: UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(models.Record).where(models.Record.user_id == user_id)
    )


def _csv_events() -> Counter:
    """(дата, время, текст) каждой строки полного CSV — прочитано напрямую, без bootstrap."""
    with DATASET_PATH.open(encoding="utf-8-sig", newline="") as fh:
        return Counter((r["date"], r["time"], r["text"]) for r in csv.DictReader(fh))


@pytest.mark.parametrize(
    ("tz_name", "done", "active", "edge_status"),
    [
        # «2026-10-25 13:15» по Москве — позже NOW (12:00 МСК), по Владивостоку — 06:15 МСК, раньше.
        ("Europe/Moscow", 693, 307, RecordStatus.ACTIVE),
        ("Asia/Vladivostok", 694, 306, RecordStatus.DONE),
    ],
)
def test_bootstrap_full_dataset(
    db: Session, tz_name: str, done: int, active: int, edge_status: RecordStatus
) -> None:
    user_id = uuid4()
    tz = ZoneInfo(tz_name)

    assert bootstrap_user_data(db, user_id, tz_name, now=NOW) == 1000
    rows = db.scalars(select(models.Record).where(models.Record.user_id == user_id)).all()
    assert len(rows) == 1000

    assert Counter(r.type for r in rows) == {
        RecordType.TASK: 761,
        RecordType.MEETING: 186,
        RecordType.REMINDER: 53,
    }
    assert Counter(r.status for r in rows) == {RecordStatus.DONE: done, RecordStatus.ACTIVE: active}
    assert all(not r.all_day and r.deadline is None and r.end is None for r in rows)

    # Каждая строка CSV — запись с тем же текстом, датой и временем в поясе пользователя.
    loaded = Counter(
        (f"{r.start.astimezone(tz):%Y-%m-%d}", f"{r.start.astimezone(tz):%H:%M}", r.title)
        for r in rows
    )
    assert loaded == _csv_events()

    (edge,) = [
        r
        for r in rows
        if r.title == "Обновить материалы по презентации"
        and r.start.astimezone(tz).date().isoformat() == "2026-10-25"
    ]
    assert edge.status is edge_status

    assert bootstrap_user_data(db, user_id, tz_name, now=NOW) == 0
    assert _count(db, user_id) == 1000


def _lock_is_free(engine: Engine, user_id: UUID) -> bool:
    """Блокировку импорта по user_id может взять другое соединение — значит, её никто не держит."""
    with engine.connect() as conn:
        taken = conn.scalar(select(func.pg_try_advisory_xact_lock(func.hashtext(str(user_id)))))
        conn.rollback()
    return taken is True


def test_bootstrap_concurrent_first_requests(engine: Engine) -> None:
    """Одновременные загрузки одному пользователю (например, два старта бэкенда создают одну
    демо-учётку) загружают датасет ровно один раз."""
    user_id = uuid4()
    workers = 4
    barrier = threading.Barrier(workers, timeout=30)

    def first_request(_: int) -> int:
        with Session(engine) as session:
            barrier.wait()
            return bootstrap_user_data(session, user_id, "Europe/Moscow", csv_path=FIXTURE, now=NOW)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = sorted(pool.map(first_request, range(workers)))
        assert results == [0, 0, 0, 5]
        with Session(engine) as session:
            assert _count(session, user_id) == 5
        assert _lock_is_free(engine, user_id)
    finally:
        with engine.begin() as conn:
            conn.execute(delete(models.Record).where(models.Record.user_id == user_id))


def test_bootstrap_error_rolls_back_and_releases_lock(engine: Engine, tmp_path: Path) -> None:
    """Ошибка посреди импорта — исключение наружу, ничего не записано, блокировка снята,
    хотя вызывающий код ещё держит сессию открытой."""
    broken = tmp_path / "broken.csv"
    broken.write_text("id,date,time,text\n1,2024-13-45,10:00,Встреча с Иваном\n", encoding="utf-8")
    user_id = uuid4()

    with Session(engine) as session:
        with pytest.raises(ValueError):
            bootstrap_user_data(session, user_id, "Europe/Moscow", csv_path=broken, now=NOW)
        assert _lock_is_free(engine, user_id)
        assert _count(session, user_id) == 0
