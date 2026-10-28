"""Стартовый датасет (backend-01b) — только для демо-учёток (backend-04).

Демо-учётка получает копию 1000 записей из `backend/data/voice_assistant_events_1000.csv`,
чтобы списки за период и поиск можно было показать сразу (`docs/decisions.md`, строка
«Датасет»). Гость и новая учётка начинают с пустого календаря; загрузку вызывает
`services/demo_accounts.py` (создание и сброс демо-учёток).

Правила интерпретации CSV:
- время в CSV — локальное время пользователя: «10:00» у любого пояса остаётся 10:00;
- тип — по тексту (`detect_type`);
- статус — `done`, если событие уже прошло на момент импорта, иначе `active`;
- повторный импорт для того же `user_id` ничего не добавляет.
"""

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, insert, select
from sqlalchemy.orm import Session

from db import models
from schemas import RecordStatus, RecordType

DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "voice_assistant_events_1000.csv"

# Встреча — по первому слову. «Встреча» встречается и в задачах («Отправить итоги встречи …»,
# «Подготовиться к встрече …»), поэтому смотрим только на начало текста.
_MEETING_FIRST_WORDS = ("встреча", "созвон", "демо", "планёрка", "планерка")
# Планёрка в датасете стоит не в начале: «Провести планёрку по …» — это встреча.
_PLANNING_ANYWHERE = re.compile(r"\bплан[её]рк", re.IGNORECASE)


def detect_type(text: str) -> RecordType:
    """Тип записи по тексту.

    - «Напомнить …» → `reminder`;
    - начинается со «Встреча», «Созвон», «Демо», «Планёрка» или содержит «планёрк…» → `meeting`;
    - всё остальное (в том числе «Позвонить …», «Отправить итоги встречи …») → `task`.
    """
    words = text.strip().lower().split()
    first = words[0] if words else ""
    if first.startswith("напомн"):
        return RecordType.REMINDER
    if first in _MEETING_FIRST_WORDS or _PLANNING_ANYWHERE.search(text):
        return RecordType.MEETING
    return RecordType.TASK


@dataclass(frozen=True)
class DatasetRow:
    day: date
    at: time
    text: str


def read_dataset(path: Path = DATASET_PATH) -> list[DatasetRow]:
    """Строки CSV (`id,date,time,text`). Кодировка с BOM: `utf-8-sig`."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [
            DatasetRow(
                day=date.fromisoformat(row["date"].strip()),
                at=time.fromisoformat(row["time"].strip()),
                text=row["text"].strip(),
            )
            for row in csv.DictReader(fh)
        ]


def _user_has_records(db: Session, user_id: UUID) -> bool:
    return db.scalar(select(exists().where(models.Record.user_id == user_id))) is True


def bootstrap_user_data(
    db_session: Session,
    user_id: UUID,
    timezone_str: str,
    *,
    csv_path: Path = DATASET_PATH,
    now: datetime | None = None,
) -> int:
    """Загрузить стартовый датасет пользователю. Возвращает число добавленных записей.

    Если у пользователя уже есть записи — ничего не делает и возвращает 0 (идемпотентность).
    Все записи вставляются одним запросом `INSERT ... VALUES (...)`.
    Неизвестный часовой пояс — `zoneinfo.ZoneInfoNotFoundError`, некорректное имя пояса
    (пустое, с `..`) — `ValueError`; оба до обращения к базе.

    Функция завершает транзакцию сессии: `commit` в обоих исходах (загрузили или пропустили),
    при ошибке — `rollback` и исключение дальше. Так блокировка по `user_id` всегда снимается,
    а сессией можно пользоваться дальше. Вызывать первой в запросе, до своих изменений.
    """
    tz = ZoneInfo(timezone_str)
    now = now or datetime.now(tz)

    try:
        # Два одновременных первых запроса одного пользователя не должны загрузить датасет
        # дважды: транзакционная блокировка по user_id, снимается при commit/rollback.
        db_session.execute(select(func.pg_advisory_xact_lock(func.hashtext(str(user_id)))))
        if _user_has_records(db_session, user_id):
            db_session.commit()
            return 0

        values = []
        for row in read_dataset(csv_path):
            start = datetime.combine(row.day, row.at, tzinfo=tz)
            values.append(
                {
                    "id": uuid4(),
                    "user_id": user_id,
                    "type": detect_type(row.text),
                    "title": row.text,
                    "start": start,
                    "all_day": False,
                    "status": RecordStatus.DONE if start < now else RecordStatus.ACTIVE,
                }
            )

        if values:
            db_session.execute(insert(models.Record).values(values))
        db_session.commit()
    except BaseException:
        db_session.rollback()
        raise
    return len(values)
