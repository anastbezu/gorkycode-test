"""Запросы к Google: OAuth и Calendar API через `httpx` (синхронно, как сервисы).

Только то, что нам нужно: ссылка согласия, обмен кода на токены, обновление и отзыв токена,
отдельный календарь, события. В тестах Google подменяется через `http_client`.
"""

import base64
import json
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .config import CALENDAR_SCOPE, EMAIL_SCOPES, GoogleConfig

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
TIMEOUT = httpx.Timeout(10.0, connect=3.0)


class GoogleError(Exception):
    """Google не ответил или ответил ошибкой — запись у нас от этого не страдает."""


class GoogleAccessRevoked(GoogleError):
    """`invalid_grant`: пользователь отозвал доступ или токен больше не действует."""


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str | None
    email: str | None


def http_client() -> httpx.Client:
    """Клиент на один вызов; тесты подменяют эту функцию клиентом с MockTransport."""
    return httpx.Client(timeout=TIMEOUT)


def authorization_url(config: GoogleConfig, state: str) -> str:
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": " ".join((CALENDAR_SCOPE, *EMAIL_SCOPES)),
        "access_type": "offline",  # нужен refresh-токен: отправлять записи без пользователя
        "prompt": "consent",  # refresh-токен выдаётся и при повторном подключении
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _email_from_id_token(id_token: str | None) -> str | None:
    """Почта из id_token. Подпись не проверяем: токен пришёл напрямую от Google по HTTPS
    в ответ на наш запрос с секретом клиента (так допускает документация OpenID Google)."""
    if not id_token:
        return None
    try:
        payload = id_token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return None
    return data.get("email")


def _post_token(config: GoogleConfig, data: dict) -> dict:
    body = {"client_id": config.client_id, "client_secret": config.client_secret, **data}
    try:
        with http_client() as client:
            response = client.post(TOKEN_URL, data=body)
    except httpx.HTTPError as error:
        raise GoogleError("Google не ответил") from error
    payload = response.json() if response.content else {}
    if response.status_code == 400 and payload.get("error") == "invalid_grant":
        raise GoogleAccessRevoked(payload.get("error_description") or "invalid_grant")
    if response.status_code != 200:
        raise GoogleError(f"Google ответил {response.status_code}: {payload.get('error')}")
    return payload


def exchange_code(config: GoogleConfig, code: str) -> Tokens:
    payload = _post_token(config, {
        "code": code, "grant_type": "authorization_code", "redirect_uri": config.redirect_uri,
    })
    return Tokens(payload["access_token"], payload.get("refresh_token"),
                  _email_from_id_token(payload.get("id_token")))


def refresh_access_token(config: GoogleConfig, refresh_token: str) -> str:
    payload = _post_token(config, {"refresh_token": refresh_token, "grant_type": "refresh_token"})
    return payload["access_token"]


def revoke(token: str) -> None:
    """Отозвать доступ в Google. Не получилось — не страшно: токен у нас всё равно удаляется."""
    try:
        with http_client() as client:
            client.post(REVOKE_URL, data={"token": token})
    except httpx.HTTPError:
        pass


def calendar_request(method: str, path: str, access_token: str, json_body: dict | None = None,
                     ) -> httpx.Response:
    try:
        with http_client() as client:
            response = client.request(method, f"{CALENDAR_API}{path}", json=json_body,
                                      headers={"Authorization": f"Bearer {access_token}"})
    except httpx.HTTPError as error:
        raise GoogleError("Google Календарь не ответил") from error
    if response.status_code == 401:
        raise GoogleAccessRevoked("Google не принял токен доступа")
    return response


def create_calendar(access_token: str, name: str) -> str:
    """Отдельный календарь приложения — разрешение calendar.app.created даёт только его."""
    response = calendar_request("POST", "/calendars", access_token, {"summary": name})
    if response.status_code != 200:
        raise GoogleError(f"Календарь не создан: {response.status_code}")
    return response.json()["id"]
