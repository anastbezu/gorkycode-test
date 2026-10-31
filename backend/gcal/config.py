"""Настройки подключения Google из окружения (`.env`, `docker-compose.yaml`).

Нет ключей — подключение выключено: маршруты отвечают 503, остальное работает как раньше.
"""

import os
from dataclasses import dataclass

# Только календари, созданные приложением: нечувствительное разрешение — без экрана
# «приложение не проверено» и без верификации у Google (проверено в Cloud Console 28.10.2026).
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"
# Почта подключённого аккаунта — показать в настройках «Подключён: …».
EMAIL_SCOPES = ("openid", "email")
CALENDAR_NAME = "Голосовой ассистент"


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    token_key: str  # ключ Fernet для шифрования refresh-токенов
    # Куда вернуть пользователя после Google: на стенде — «/» (тот же домен), локально —
    # адрес Vite, напр. http://localhost:5173/. К адресу добавляется ?calendar=connected|error.
    return_url: str = "/"


def google_config() -> GoogleConfig | None:
    """Настройки или `None`, если чего-то не хватает (подключение выключено)."""
    values = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", "").strip(),
        "token_key": os.getenv("GOOGLE_TOKEN_KEY", "").strip(),
    }
    if not all(values.values()):
        return None
    return GoogleConfig(**values, return_url=os.getenv("GOOGLE_RETURN_URL", "").strip() or "/")
