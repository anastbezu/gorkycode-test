"""Gemini Interactions TTS: полный WAV в памяти, без повторов и записи на диск."""

import asyncio
import base64
import binascii
import io
import json
import os
import wave

import httpx

API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_BYTES = 12 * 1024 * 1024
MAX_AUDIO_BYTES = 8 * 1024 * 1024


class TTSUnavailableError(Exception):
    """Безопасная причина сбоя, без ключа, текста пользователя и ответа провайдера."""


def settings() -> tuple[str, str, str]:
    if os.getenv("TTS_ENABLED", "1").strip().lower() not in {"1", "true", "yes"}:
        raise TTSUnavailableError("сервис выключен")
    key = os.getenv("TTS_API_KEY", "").strip()
    model = os.getenv("TTS_MODEL", "gemini-3.8-flash-lite-tts").strip()
    voice = os.getenv("TTS_VOICE", "Kore").strip()
    if not key or not model or not voice:
        raise TTSUnavailableError("не заданы настройки TTS")
    return key, model, voice


def parse_audio(payload: dict) -> bytes:
    blocks = [
        block
        for step in payload.get("steps", [])
        if step.get("type") == "model_output"
        for block in step.get("content", [])
        if block.get("type") == "audio"
    ]
    if not blocks or blocks[-1].get("mime_type", "audio/wav") != "audio/wav":
        raise ValueError("no WAV output")
    data = base64.b64decode(blocks[-1]["data"], validate=True)
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise ValueError("invalid audio size")
    with wave.open(io.BytesIO(data), "rb") as wav:
        frames = wav.getnframes()
        width, channels = wav.getsampwidth(), wav.getnchannels()
        if width != 2 or channels not in {1, 2} or wav.getframerate() <= 0 or frames <= 0:
            raise ValueError("invalid PCM format")
        if len(wav.readframes(frames)) != frames * width * channels:
            raise ValueError("truncated audio")
    return data


async def synthesize(text: str) -> bytes:
    key, model, voice = settings()
    body = {
        "model": model,
        "input": [{"type": "user_input", "content": [{"type": "text", "text": text}]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    try:
        # Общий дедлайн, а не только таймаут между чанками ответа.
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                async with client.stream(
                    "POST", API_URL, headers={"x-goog-api-key": key}, json=body
                ) as response:
                    if response.status_code != 200:
                        raise TTSUnavailableError(f"ответ провайдера {response.status_code}")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE_BYTES:
                            raise TTSUnavailableError("слишком большой ответ провайдера")
        return parse_audio(json.loads(raw))
    except (httpx.HTTPError, TimeoutError) as exc:
        raise TTSUnavailableError("сеть или таймаут") from exc
    except (
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        binascii.Error,
        wave.Error,
        EOFError,
    ) as exc:
        raise TTSUnavailableError("повреждённый ответ провайдера") from exc
