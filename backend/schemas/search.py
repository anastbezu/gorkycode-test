"""Результаты поиска.

Контракт: docs/contracts/search.md. Функции search() и find_target() — в модуле поиска (Родион).
"""

from typing import Literal

from pydantic import BaseModel

from .record import Record


class SearchHit(BaseModel):
    record: Record
    score: float
    match: Literal["exact", "similar"] = "exact"  # «точно» или «похоже по смыслу»


class TargetMatch(BaseModel):
    exact: list[Record] = []  # подходят точно — по ним можно действовать
    similar: list[Record] = []  # похожи по смыслу — только предложить вопросом
