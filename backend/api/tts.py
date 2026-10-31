"""POST /api/tts: текст ответа → WAV, ошибки не затрагивают действие агента."""

import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

from stt.rate_limit import RateLimiter
from tts import TTSUnavailableError, synthesize

from .deps import USER_ID_HEADER, CurrentUser, get_current_user_id

logger = logging.getLogger(__name__)


class TTSRoute(APIRoute):
    """Строковый detail по контракту TTS, включая ошибку разбора JSON."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": "Нужен text: непустая строка до 1000 символов, без лишних полей."
                    },
                )

        return handle


router = APIRouter(prefix="/api", tags=["voice"], route_class=TTSRoute)
rate_limiter = RateLimiter(15, 60)
global_rate_limiter = RateLimiter(120, 60)


class TTSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(strict=True, min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def not_blank(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("text не должен быть пустым")
        return text  # reply передаётся дословно, без trim и переписывания дат


@router.post(
    "/tts",
    response_class=Response,
    summary="Озвучить ответ ассистента",
    responses={
        200: {"content": {"audio/wav": {}}, "description": "Полный WAV PCM16"},
        400: {"description": "X-User-Id не UUID"},
        401: {"description": "Токен учётки недействителен"},
        422: {"description": "Некорректный JSON или text"},
        429: {"description": "Лимит пользователя или сервера"},
        503: {"description": "Сервис озвучки недоступен"},
    },
)
async def text_to_speech(
    body: TTSRequest,
    user: Annotated[CurrentUser, Depends(get_current_user_id)],
) -> Response:
    for limiter, key in ((rate_limiter, user.id), (global_rate_limiter, "all")):
        retry = limiter.hit(key)
        if retry is not None:
            raise HTTPException(
                429,
                "Слишком много запросов озвучки.",
                headers={"Retry-After": str(max(1, int(retry) + 1))},
            )
    try:
        audio = await synthesize(body.text)
    except TTSUnavailableError as exc:
        logger.warning("TTS недоступно: %s", exc)
        raise HTTPException(503, "Озвучка сейчас недоступна.") from exc
    headers = {"Cache-Control": "no-store"}
    # Возвращаем собственный Response: заголовки dependency нужно перенести явно.
    if not user.is_account:
        headers[USER_ID_HEADER] = str(user.id)
    return Response(content=audio, media_type="audio/wav", headers=headers)
