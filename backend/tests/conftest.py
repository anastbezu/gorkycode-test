"""Общие фикстуры тестов.

Тестам с базой нужен PostgreSQL. Адрес — `TEST_DATABASE_URL` или `DATABASE_URL`
(например, база из `docker compose up -d postgres`). Нет базы — такие тесты пропускаются.
Схема создаётся миграциями (`alembic upgrade head`), каждый тест работает в транзакции,
которая откатывается — данные в базе не остаются.

Модель поиска по смыслу во всех тестах подменена кодировщиком по словам (`fake_search_vectors`):
тесты агента и сервисов не зависят от её файлов, в CI их нет. Настоящую модель включает
метка `@pytest.mark.search_model` — так работают тесты качества поиска.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from alembic import command, config
from db.session import database_url

BACKEND_DIR = Path(__file__).resolve().parents[1]


def fake_search_vectors(texts: list[str]) -> np.ndarray:
    """Вектор текста без модели: каждое слово — своё измерение (по хэшу слова).

    Тексты с общими словами похожи, без общих — нет; одинаковый текст — одинаковый вектор.
    """
    from db.models import EMBEDDING_DIM

    out = np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)
    for i, text_ in enumerate(texts):
        for word in text_.lower().split() or [""]:
            out[i, sum(map(ord, word)) % EMBEDDING_DIM] += 1.0
    return out / np.linalg.norm(out, axis=1, keepdims=True)


@pytest.fixture(autouse=True)
def _search_model(request, monkeypatch):
    if request.node.get_closest_marker("search_model"):
        return
    from search import embeddings

    monkeypatch.setattr(embeddings, "embed_queries", fake_search_vectors)
    monkeypatch.setattr(embeddings, "embed_documents", fake_search_vectors)


def _test_db_url() -> str | None:
    if url := os.environ.get("TEST_DATABASE_URL"):
        os.environ["DATABASE_URL"] = url
    try:
        return database_url()
    except RuntimeError:
        return None


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = _test_db_url()
    if url is None:
        pytest.skip("нет DATABASE_URL / TEST_DATABASE_URL — тесты с БД пропущены")
    eng = create_engine(url)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL недоступен ({url}): {exc.orig}")

    cfg = config.Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """Сессия внутри транзакции, которая откатывается после теста."""
    with engine.connect() as conn:
        trans = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            trans.rollback()
