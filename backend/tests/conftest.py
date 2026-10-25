"""Общие фикстуры тестов.

Тестам с базой нужен PostgreSQL. Адрес — `TEST_DATABASE_URL` или `DATABASE_URL`
(например, база из `docker compose up -d postgres`). Нет базы — такие тесты пропускаются.
Схема создаётся миграциями (`alembic upgrade head`), каждый тест работает в транзакции,
которая откатывается — данные в базе не остаются.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from alembic import command, config
from db.session import database_url

BACKEND_DIR = Path(__file__).resolve().parents[1]


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
