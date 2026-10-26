"""Точка входа бэкенда (FastAPI).

Запуск из папки backend/:
    uv run uvicorn main:app --reload
Документация API (Swagger): http://localhost:8000/docs
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import chat, health, items, stt
from api.deps import USER_ID_HEADER

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


app = FastAPI(
    title="Голосовой ассистент для задач и встреч",
    version="0.1.0",
    description=(
        "API чата, распознавания речи и панели «Мои дела». Пользователь — анонимный UUID "
        "браузера в заголовке `X-User-Id`: без заголовка сервер выдаёт новый в заголовке ответа."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    # Без этого браузер не даст фронтенду прочитать выданный X-User-Id из ответа.
    expose_headers=[USER_ID_HEADER],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(items.router)
app.include_router(stt.router)
