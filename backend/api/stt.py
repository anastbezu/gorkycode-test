"""`POST /api/stt` — распознавание речи (контракт docs/contracts/api.md, «Распознавание речи»).

Голос идёт в два шага: запись → `/api/stt` → текст → обычный `POST /api/chat`. Ошибки
распознавания остаются здесь и до агента не доходят. Ответ с ошибкой — статус и
`{"detail": "<текст для пользователя>"}`: интерфейс показывает `detail` как есть.
"""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from starlette.formparsers import MultiPartParser

from schemas import STTResponse
from stt import (
    ALLOWED_TYPES,
    RateLimiter,
    STTUnavailableError,
    duration_seconds,
    matches_signature,
    normalize_content_type,
    transcribe,
)

from .deps import CurrentUser, get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["voice"])

# Запись длиннее 30 секунд — 413 (контракт api.md), без запаса.
MAX_SECONDS = 30
# Короче — точно не фраза (случайное нажатие): отвечаем «не расслышал», не тратя лимит.
MIN_SECONDS = 0.3
# Если длительность из файла не прочиталась — ограничение по размеру: 30 с при 320 кбит/с.
# Запись Chrome (opus, 128 кбит/с) за 30 с весит около 0,5 МБ.
MAX_BYTES_WITHOUT_DURATION = MAX_SECONDS * 320_000 // 8
# Предел файла вообще: 30 с несжатого WAV (48 кГц, стерео) — около 5,8 МБ.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Частота: несколько голосовых реплик в минуту — норма живого разговора. Одна реплика — это
# запись и 2–5 с распознавания, так что больше 10–15 в минуту живой человек не наговорит.
RATE_LIMIT_REQUESTS = 15
RATE_LIMIT_WINDOW_SECONDS = 60
# Общий предел на весь сервер — защита серверного ключа: без `X-User-Id` каждый запрос получает
# новый id, и лимит на пользователя не действует. 120 в минуту — восемь человек, которые
# говорят без пауз; на демо и проверке столько одновременно не бывает.
GLOBAL_RATE_LIMIT_REQUESTS = 120

# Запись не пишется на диск: Starlette по умолчанию сбрасывает файл больше 1 МБ во временный
# файл — поднимаем этот порог до предела загрузки, и запись целиком остаётся в памяти.
MultiPartParser.spool_max_size = MAX_UPLOAD_BYTES

rate_limiter = RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)
global_rate_limiter = RateLimiter(GLOBAL_RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)

NOT_RECOGNIZED = "Не расслышал, повторите, пожалуйста."


def _error(code: int, detail: str, headers: dict[str, str] | None = None) -> HTTPException:
    return HTTPException(status_code=code, detail=detail, headers=headers)


@router.post(
    "/stt",
    response_model=STTResponse,
    summary="Распознать голосовую запись",
    responses={
        400: {"description": "Заголовок X-User-Id не UUID"},
        413: {"description": "Запись длиннее 30 секунд"},
        415: {"description": "Формат файла не из списка или поле `audio` пустое"},
        422: {"description": "Речь не распознана: тишина, шум, пустой результат"},
        429: {"description": "Слишком много запросов от пользователя или от всех вместе"},
        503: {"description": "Сервис распознавания недоступен или не задан ключ"},
    },
)
async def speech_to_text(
    user: Annotated[CurrentUser, Depends(get_current_user_id)],
    # Тип без `| None`: тогда /docs рисует выбор файла. Поле необязательное, чтобы его
    # отсутствие давало 415 по контракту, а не общую ошибку валидации FastAPI (422).
    audio: Annotated[
        UploadFile,
        File(
            description="Запись из MediaRecorder: audio/webm, audio/mp4, audio/ogg или "
            "audio/wav, не длиннее 30 секунд. Формат — из Content-Type файла."
        ),
    ] = None,
) -> STTResponse:
    retry_after = rate_limiter.hit(user.id)
    if retry_after is not None:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Слишком много голосовых запросов подряд — подождите немного и повторите.",
            headers={"Retry-After": str(max(int(retry_after) + 1, 1))},
        )
    # После лимита пользователя: его отклонённые запросы общий предел не расходуют.
    retry_after = global_rate_limiter.hit("all")
    if retry_after is not None:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Сейчас слишком много голосовых запросов — подождите немного или напишите текстом.",
            headers={"Retry-After": str(max(int(retry_after) + 1, 1))},
        )

    content_type = normalize_content_type(audio.content_type if audio else None)
    if audio is not None and content_type not in ALLOWED_TYPES:
        raise _error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Такой формат записи не поддерживается — нужен audio/webm, audio/mp4, "
            "audio/ogg или audio/wav.",
        )
    data = await audio.read(MAX_UPLOAD_BYTES + 1) if audio is not None else b""
    if not data:
        raise _error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Запись пустая — попробуйте ещё раз.")
    if not matches_signature(data, content_type):
        raise _error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Файл не похож на аудиозапись — попробуйте записать ещё раз.",
        )

    too_long = _error(
        status.HTTP_413_CONTENT_TOO_LARGE,
        f"Запись длиннее {MAX_SECONDS} секунд — скажите короче или разбейте на несколько фраз.",
    )
    if len(data) > MAX_UPLOAD_BYTES:
        raise too_long
    # Разбор заголовков — синхронный цикл по файлу до 10 МБ: в потоке, чтобы не держать
    # сервер (и `/api/chat` других пользователей), пока он идёт.
    seconds = await asyncio.to_thread(duration_seconds, data, content_type)
    if seconds is None:
        if len(data) > MAX_BYTES_WITHOUT_DURATION:
            raise too_long
    elif seconds > MAX_SECONDS:
        raise too_long
    elif seconds < MIN_SECONDS:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, NOT_RECOGNIZED)

    try:
        text = await transcribe(data, content_type)
    except STTUnavailableError as exc:
        logger.warning("STT недоступно: %s", exc)
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Распознавание речи сейчас недоступно — попробуйте позже или напишите текстом.",
        ) from exc
    if not text:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, NOT_RECOGNIZED)
    return STTResponse(text=text)
