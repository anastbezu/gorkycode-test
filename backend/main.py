"""Точка входа бэкенда.

Запуск локально (из папки backend/):
    pip install -r requirements.txt
    uvicorn main:app --reload
Swagger: http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router

app = FastAPI(
    title="Голосовой ассистент для задач и встреч",
    version="0.1.0",
    description="Сейчас эндпоинты — заглушки с фиксированными ответами.",
)

# Локально фронт на :3000, бэк на :8000 — разные origin. На сервере всё за одним Nginx.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
