"""Распознавание речи для `POST /api/stt`: проверка записи, лимит частоты, клиент провайдера.

Не агент: агент получает уже готовый текст через обычный `POST /api/chat`.
"""

from .audio import ALLOWED_TYPES, duration_seconds, matches_signature, normalize_content_type
from .client import STTUnavailableError, transcribe
from .rate_limit import RateLimiter

__all__ = [
    "ALLOWED_TYPES",
    "RateLimiter",
    "STTUnavailableError",
    "duration_seconds",
    "matches_signature",
    "normalize_content_type",
    "transcribe",
]
