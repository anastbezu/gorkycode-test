"""Срок хранения — 30 дней (контракт api.md, «Учётки и вход»; backend-04).

- Гость, от которого 30 дней не было запросов, удаляется вместе с записями и разговорами.
- Запись, отменённая больше 30 дней назад, удаляется насовсем — у гостей и у учёток.
- Учётки и демо-учётки не удаляются никогда; истёкшие токены входа удаляются.

Чистка повторяемая: второй запуск подряд ничего не находит и ничего не ломает.
Запускается сама при старте бэкенда и потом раз в 6 часов (`main.py`), вручную —
`python -m scripts.cleanup`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from db import models
from schemas import RecordStatus

RETENTION = timedelta(days=30)


@dataclass(frozen=True)
class CleanupResult:
    guests: int
    records: int  # отменённые записи учёток и гостей, которые остаются
    tokens: int


def cleanup(db: Session, *, now: datetime | None = None) -> CleanupResult:
    """Удалить всё, что старше срока хранения, одной транзакцией. Коммитит сам."""
    now = now or datetime.now(UTC)
    cutoff = now - RETENTION
    users, records, states = models.User, models.Record, models.ConversationState

    stale_guests = select(users.id).where(users.login.is_(None), users.last_seen_at < cutoff)
    try:
        db.execute(delete(states).where(states.user_id.in_(stale_guests)))
        db.execute(delete(records).where(records.user_id.in_(stale_guests)))
        guests = db.execute(delete(users).where(users.id.in_(stale_guests))).rowcount
        old_cancelled = db.execute(
            delete(records).where(
                records.status == RecordStatus.CANCELLED, records.cancelled_at < cutoff
            )
        ).rowcount
        tokens = db.execute(
            delete(models.AuthToken).where(models.AuthToken.expires_at <= now)
        ).rowcount
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return CleanupResult(guests=guests, records=old_cancelled, tokens=tokens)
