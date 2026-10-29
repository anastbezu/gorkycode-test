"""Векторы названий в таблице `text_embeddings`: досчитать недостающие и сравнить с запросом.

Вектор хранится на текст (docs/modules/search.md): ключ — модель и md5 текста.
Модуль поиска досчитывает тексты без вектора сам, прямо перед сравнением; сервисы записей
поиск не вызывают.
Запись идёт в транзакции вызывающего (контракт `search.md`): векторы сохраняются вместе
с репликой — один коммит на реплику (`docs/decisions.md`, «Доступ к БД»).
"""

import hashlib
import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db.models import TextEmbedding

from . import embeddings

logger = logging.getLogger(__name__)


def text_hash(text: str) -> str:
    """md5 текста в hex — то же, что `md5(title)` в Postgres (база в UTF-8). Ключ, не защита."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def ensure_vectors(db: Session, texts: list[str]) -> int:
    """Досчитать векторы текстов, которых ещё нет в базе. Возвращает, сколько посчитано.

    Два одновременных запроса могут посчитать один текст дважды — второй `INSERT` ничего
    не сделает (`ON CONFLICT DO NOTHING`), вектор один и тот же.
    """
    by_hash = {text_hash(t): t for t in texts}
    if not by_hash:
        return 0
    known = set(
        db.scalars(
            select(TextEmbedding.text_hash).where(
                TextEmbedding.model == embeddings.MODEL_KEY,
                TextEmbedding.text_hash.in_(by_hash),
            )
        )
    )
    missing = [(h, t) for h, t in by_hash.items() if h not in known]
    if not missing:
        return 0

    vectors = embeddings.embed_documents([t for _, t in missing])
    db.execute(
        insert(TextEmbedding)
        .values(
            [
                {"model": embeddings.MODEL_KEY, "text_hash": h, "text": t, "embedding": v}
                for (h, t), v in zip(missing, vectors, strict=True)
            ]
        )
        .on_conflict_do_nothing(index_elements=["model", "text_hash"])
    )
    logger.info("поиск: посчитано векторов %d (%s)", len(missing), embeddings.MODEL_KEY)
    return len(missing)


def similarities(db: Session, query_vector: np.ndarray, texts: list[str]) -> dict[str, float]:
    """Косинусное сходство запроса с каждым текстом: {текст: сходство}.

    Векторы должны быть посчитаны (`ensure_vectors`). Сходство считает pgvector:
    `<=>` — косинусное расстояние, сходство = 1 − расстояние.
    """
    by_hash = {text_hash(t): t for t in texts}
    if not by_hash:
        return {}
    similarity = 1 - TextEmbedding.embedding.cosine_distance(query_vector)
    rows = db.execute(
        select(TextEmbedding.text_hash, similarity).where(
            TextEmbedding.model == embeddings.MODEL_KEY,
            TextEmbedding.text_hash.in_(by_hash),
        )
    )
    return {by_hash[h]: float(s) for h, s in rows}
