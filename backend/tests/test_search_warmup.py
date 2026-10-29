"""Прогрев поиска (`search/warmup.py`): векторы стартового набора считаются один раз."""

from sqlalchemy import func, select

from db.models import TextEmbedding
from search import embeddings, vectors
from search.warmup import warm_up
from services.bootstrap import read_dataset


def test_warm_up_computes_start_dataset_vectors_once(db, monkeypatch):
    # warm_up коммитит сам; в тестовой сессии это коммит точки сохранения — откатится.
    loaded = []
    real = embeddings.embed_queries
    monkeypatch.setattr(
        embeddings, "embed_queries", lambda texts: loaded.append(texts) or real(texts)
    )
    titles = {row.text for row in read_dataset()}

    first = warm_up(db)
    stored = db.scalar(select(func.count()).select_from(TextEmbedding).where(
        TextEmbedding.model == embeddings.MODEL_KEY,
        TextEmbedding.text_hash.in_([vectors.text_hash(t) for t in titles]),
    ))

    assert first == len(titles) == stored == 376
    assert warm_up(db) == 0  # второй старт сервера ничего не пересчитывает
    assert len(loaded) == 2  # модель загружается при каждом старте
