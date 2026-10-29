"""Ошибки валидации запроса (422) — текстом для пользователя там, где этого требует контракт.

FastAPI по умолчанию отвечает на тело не по схеме списком ошибок. Контракт `api.md` для входа
(«Учётки и вход») и кнопок записей («Записи из интерфейса») требует `{"detail": "<текст>"}`.
Остальные маршруты отвечают как раньше — стандартным обработчиком FastAPI.
"""

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import auth, items


async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    path = request.url.path
    if path.startswith(auth.router.prefix + "/"):
        return await auth.credentials_validation_handler(request, exc)
    if items.is_item_change(request.method, path):
        return items.item_validation_response(exc)
    return await request_validation_exception_handler(request, exc)
