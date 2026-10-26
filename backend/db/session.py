"""Подключение к PostgreSQL: движок и фабрика сессий (синхронный psycopg 3).

URL берётся из переменной окружения `DATABASE_URL` (или файла `.env`).
"""

import os
from collections.abc import Iterator
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv(find_dotenv(usecwd=True))


def database_url() -> str:
    """`DATABASE_URL` с драйвером psycopg 3.

    В `.env.example` адрес вида `postgresql://...` — без указания драйвера SQLAlchemy
    искал бы psycopg2, которого у нас нет. Подставляем `postgresql+psycopg://`.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL не задан: скопируйте .env.example в .env")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


# Без таймаута подключение к недоступной базе висит до таймаута TCP (~2 минуты):
# `/health` и запросы пользователя ждали бы его вместо быстрого 503 / ошибки.
CONNECT_TIMEOUT_S = 5


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        database_url(), pool_pre_ping=True, connect_args={"connect_timeout": CONNECT_TIMEOUT_S}
    )


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def SessionLocal() -> Session:  # noqa: N802 — привычное имя фабрики
    """Новая сессия. Использовать как контекстный менеджер: `with SessionLocal() as db: ...`."""
    return _session_factory()()


def get_session() -> Iterator[Session]:
    """Зависимость FastAPI: одна сессия на запрос, закрывается после ответа."""
    with SessionLocal() as session:
        yield session
