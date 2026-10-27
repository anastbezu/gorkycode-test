"""ВРЕМЕННАЯ заглушка смыслового поиска: поиск по подстроке в названии.

Живёт до модуля поиска Родиона (docs/contracts/search.md). Сигнатура повторяет контракт
плюс `db` первым аргументом, потому что заглушке нужна сессия базы.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import models
from schemas import Record, RecordStatus, SearchFilters, SearchHit, TargetMatch

MIN_WORD_LEN = 2


def query_words(query: str) -> list[str]:
    """Слова запроса, по которым ищем: короткие предлоги («с», «о») отбрасываем."""
    return [w for w in query.split() if len(w) > MIN_WORD_LEN]


def like_pattern(word: str) -> str:
    """Подстрока для ILIKE, где `%` и `_` в самом слове не работают как подстановки."""
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_by_substring(
        db: Session, user_id: UUID, query: str, filters: SearchFilters, limit: int = 10
) -> list[SearchHit]:
    words = query_words(query)
    if not words:
        return []

    m = models.Record
    when = func.coalesce(m.start, m.deadline, m.created_at)
    stmt = select(m).where(m.user_id == user_id)
    for word in words:
        stmt = stmt.where(m.title.ilike(like_pattern(word), escape="\\"))

    if filters.status:
        stmt = stmt.where(m.status.in_(filters.status))
    else:
        stmt = stmt.where(m.status != RecordStatus.CANCELLED)
    if filters.types:
        stmt = stmt.where(m.type.in_(filters.types))
    if filters.date_from is not None:
        stmt = stmt.where(when >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(when < filters.date_to)

    stmt = stmt.order_by(when.desc()).limit(limit)
    return [SearchHit(record=Record.model_validate(r), score=1.0) for r in db.scalars(stmt).all()]


def _narrow_by_when(records: list[Record], when: datetime) -> list[Record]:
    """Сужение по названному времени: день и время → тот же день → то же время."""
    def local(record: Record) -> datetime | None:
        moment = record.start or record.deadline
        return moment.astimezone(when.tzinfo) if moment is not None else None

    day_only = (when.hour, when.minute) == (0, 0)
    same_moment = [r for r in records if (m := local(r)) is not None
                   and (m.date(), m.hour, m.minute) == (when.date(), when.hour, when.minute)]
    same_day = [r for r in records if (m := local(r)) is not None and m.date() == when.date()]
    same_time = [r for r in records if (m := local(r)) is not None
                 and (m.hour, m.minute) == (when.hour, when.minute)]
    tiers = [same_day] if day_only else [same_moment, same_day, same_time]
    return next((tier for tier in tiers if tier), [])


def find_target(
        db: Session, user_id: UUID, text: str | None, when: datetime | None,
        filters: SearchFilters | None, statuses: list[RecordStatus], limit: int = 21,
) -> TargetMatch:
    """ВРЕМЕННАЯ заглушка find_target() из search.md: «точно» — все слова в названии.

    Похожих по смыслу заглушка не находит: `similar` — только точные по словам записи,
    которые не подошли под названное время (как в контракте).
    """
    m = models.Record
    stmt = select(m).where(m.user_id == user_id, m.status.in_(statuses))
    for word in query_words(text or ""):
        stmt = stmt.where(m.title.ilike(like_pattern(word), escape="\\"))
    if filters is not None:
        if filters.types:
            stmt = stmt.where(m.type.in_(filters.types))
        moment = func.coalesce(m.start, m.deadline)
        if filters.date_from is not None:
            stmt = stmt.where(moment >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(moment < filters.date_to)
    order = func.coalesce(m.start, m.deadline)
    stmt = stmt.order_by(order.is_(None), order, m.created_at)
    records = [Record.model_validate(r) for r in db.scalars(stmt).all()]
    if when is None:
        return TargetMatch(exact=records[:limit])
    exact = _narrow_by_when(records, when)
    if exact or not text:
        return TargetMatch(exact=exact[:limit])
    return TargetMatch(similar=records[:3])
