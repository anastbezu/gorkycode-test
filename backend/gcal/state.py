"""`state` для OAuth: связывает возврат от Google с учёткой, которая начала подключение.

Подписан HMAC ключом `GOOGLE_TOKEN_KEY` и живёт 10 минут: чужую ссылку возврата не подделать
и не переиспользовать надолго. Таблица для него не нужна.
"""

import base64
import hashlib
import hmac
from datetime import datetime, timedelta
from uuid import UUID

STATE_TTL = timedelta(minutes=10)


def _sign(payload: str, key: str) -> str:
    digest = hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def make_state(user_id: UUID, key: str, now: datetime) -> str:
    payload = f"{user_id}.{int((now + STATE_TTL).timestamp())}"
    return f"{payload}.{_sign(payload, key)}"


def read_state(state: str, key: str, now: datetime) -> UUID | None:
    """Учётка из `state` или `None`: подпись не сходится, истёк, не тот формат."""
    try:
        user, expires, signature = state.split(".")
        payload = f"{user}.{expires}"
        if not hmac.compare_digest(signature, _sign(payload, key)):
            return None
        if int(expires) < now.timestamp():
            return None
        return UUID(user)
    except ValueError:
        return None
