"""ВРЕМЕННАЯ заглушка смыслового поиска: поиск по подстроке в названии.

Живёт до модуля поиска Родиона (docs/contracts/search.md). Сигнатура повторяет контракт
плюс `db` первым аргументом, потому что заглушке нужна сессия базы.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import models
from schemas import Record, RecordStatus, SearchFilters, SearchHit

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
