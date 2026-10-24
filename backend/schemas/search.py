"""Результат поиска.

Контракт: docs/contracts/search.md. Сама функция search() — в модуле поиска (Родион).
"""

from pydantic import BaseModel

from .record import Record


class SearchHit(BaseModel):
    record: Record
    score: float
