"""Клиент распознавания речи: Gemini, нативный API (`generateContent`).

Ключ и модель — из окружения (`STT_API_KEY`, `STT_MODEL`), отдельно от `LLM_*`: распознавание
всегда идёт на серверном ключе, пользовательские настройки LLM его не касаются.
`STT_THINKING_LEVEL` — необязательный уровень «обдумывания» модели; пусто — как решит Gemini.

Почему нативный API, а не OpenAI-совместимый адрес агента — в docs/modules/backend.md,
раздел «Распознавание речи».
"""

import base64
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT_SECONDS = 25.0

# Gemini называет AAC в контейнере MP4 «audio/m4a»; «audio/mp4» в его списке форматов нет.
_GEMINI_MIME = {"audio/mp4": "audio/m4a"}

PROMPT = (
    "Расшифруй речь в аудиозаписи дословно, на русском языке, как она звучит: без пересказа, "
    "сокращений и исправлений. Не добавляй ничего от себя. Если речи нет — тишина, шум, "
    "музыка, неразборчиво — верни пустой text."
)


class STTUnavailableError(Exception):
    """Сервис распознавания недоступен: не задан ключ или модель, сеть, таймаут, лимит."""


def _settings() -> tuple[str, str, str]:
    api_key = os.getenv("STT_API_KEY", "").strip()
    model = os.getenv("STT_MODEL", "").strip()
    thinking_level = os.getenv("STT_THINKING_LEVEL", "").strip()
    if not api_key:
        raise STTUnavailableError("не задан STT_API_KEY")
    if not model:
        raise STTUnavailableError("не задан STT_MODEL")
    return api_key, model, thinking_level


async def transcribe(audio: bytes, content_type: str) -> str:
    """Текст записи; пустая строка — речь не распознана.

    Любая ошибка провайдера — `STTUnavailableError`: пользователю она одинакова
    («сервис недоступен, попробуйте позже»), подробности — в лог сервера.
    """
    api_key, model, thinking_level = _settings()
    generation_config: dict = {
        "temperature": 0,
        # Ответ — JSON по схеме: так пустой результат («речи нет») не спутать с пояснением
        # модели вроде «В записи тишина».
        "responseMimeType": "application/json",
        "responseSchema": {
            "type": "OBJECT",
            "properties": {"text": {"type": "STRING"}},
            "required": ["text"],
        },
    }
    if thinking_level:
        # Допустимые значения зависят от модели (у одной есть `minimal`, у другой нет),
        # поэтому по умолчанию не задаём: Gemini берёт уровень, заданный для модели.
        generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    body = {
        "systemInstruction": {"parts": [{"text": PROMPT}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": _GEMINI_MIME.get(content_type, content_type),
                            "data": base64.b64encode(audio).decode("ascii"),
                        }
                    }
                ],
            }
        ],
        "generationConfig": generation_config,
    }
    url = f"{GEMINI_API_URL}/models/{model}:generateContent"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers={"x-goog-api-key": api_key}, json=body)
    except httpx.HTTPError as exc:
        raise STTUnavailableError(f"сеть или таймаут: {type(exc).__name__}") from exc
    if response.status_code != 200:
        # Ключ в URL не передаётся — в лог попадает только ответ провайдера.
        logger.warning("Gemini STT: %s %s", response.status_code, response.text[:500])
        raise STTUnavailableError(f"ответ провайдера {response.status_code}")
    return _parse_text(response.json())


def _parse_text(payload: dict) -> str:
    """Текст из ответа `generateContent`. Нет кандидатов (фильтр, пустой ответ) — пусто."""
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    raw = "".join(part.get("text", "") for part in parts).strip()
    if not raw:
        return ""
    try:
        text = json.loads(raw).get("text", "")
    except (json.JSONDecodeError, AttributeError):
        # Модель ответила не по схеме — берём текст как есть: это всё равно расшифровка.
        text = raw
    return text.strip() if isinstance(text, str) else ""
