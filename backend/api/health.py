"""`GET /health` — жив ли сервер и есть ли связь с PostgreSQL."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

router = APIRouter(tags=["service"])


@router.get(
    "/health",
    responses={
        200: {"content": {"application/json": {"example": {"status": "ok", "db": "connected"}}}},
        503: {"description": "База данных недоступна"},
    },
)
def health() -> JSONResponse:
    """`SELECT 1` в базе: 200 — подключение есть, 503 — нет (или не задан `DATABASE_URL`)."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except (SQLAlchemyError, RuntimeError):
        return JSONResponse(status_code=503, content={"status": "error", "db": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ok", "db": "connected"})
