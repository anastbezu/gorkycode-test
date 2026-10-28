"""Точка входа бэкенда (FastAPI).

Запуск из папки backend/:
    uv run uvicorn main:app --reload
Документация API (Swagger): http://localhost:8000/docs
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from api import auth, chat, health, items, stt
from api.deps import USER_ID_HEADER
from db import SessionLocal
from services.demo_accounts import ensure_demo_accounts, parse_demo_accounts
from services.retention import cleanup

# Логгер uvicorn: сообщения при старте видны в логах контейнера рядом с логами сервера.
log = logging.getLogger("uvicorn.error")

CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60

# Фронтенд на стенде и при локальной разработке. Можно переопределить через CORS_ORIGINS
# (через запятую), не меняя кода.
DEFAULT_CORS_ORIGINS = [
    "https://gorky.bond",
    "https://www.gorky.bond",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    custom = [o.strip() for o in raw.split(",") if o.strip()]
    return custom or DEFAULT_CORS_ORIGINS


def _ensure_demo_accounts() -> None:
    """Демо-учётки из `DEMO_ACCOUNTS` — при каждом старте: недостающие создаются с датасетом.
    Ошибка (база недоступна, переменная записана неверно) — в лог; сервер всё равно стартует."""
    try:
        accounts = parse_demo_accounts()
        if not accounts:
            return
        with SessionLocal() as db:
            result = ensure_demo_accounts(db, accounts)
        if result.created or result.updated_password or result.refilled:
            log.info(
                "Демо-учётки: созданы %s, обновлён пароль %s, датасет загружен заново %s",
                result.created or "—",
                result.updated_password or "—",
                result.refilled or "—",
            )
    except Exception:
        log.exception("Демо-учётки не созданы")


def _cleanup_once() -> None:
    try:
        with SessionLocal() as db:
            result = cleanup(db)
        if result.guests or result.records or result.tokens:
            log.info(
                "Чистка: гостей %s, отменённых записей %s, токенов %s",
                result.guests,
                result.records,
                result.tokens,
            )
    except Exception:
        log.exception("Чистка по сроку хранения не выполнена")


async def _cleanup_loop() -> None:
    """Чистка по сроку хранения: при старте и потом раз в 6 часов (бэкенд один)."""
    while True:
        await asyncio.to_thread(_cleanup_once)
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(_ensure_demo_accounts)
    cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()


app = FastAPI(
    title="Голосовой ассистент для задач и встреч",
    version="0.1.0",
    description=(
        "API чата, распознавания речи и панели «Мои дела». Пользователь — учётка по токену "
        "в `Authorization: Bearer <token>` (`/api/auth/*`) или гость по UUID браузера в "
        "заголовке `X-User-Id`: без заголовка сервер выдаёт новый в заголовке ответа."
    ),
    lifespan=lifespan,
)
app.add_exception_handler(RequestValidationError, auth.credentials_validation_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],  # в том числе Authorization: «*» Starlette отвечает списком из запроса
    # Без этого браузер не даст фронтенду прочитать выданный X-User-Id из ответа.
    expose_headers=[USER_ID_HEADER],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(items.router)
app.include_router(stt.router)
