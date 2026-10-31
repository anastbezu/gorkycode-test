"""Google Календарь у учётки (calendar-01). Контракт: docs/contracts/api.md, «Внешний календарь»."""

from typing import Literal

from pydantic import BaseModel


class GoogleCalendarStatus(BaseModel):
    state: Literal["not_connected", "connected", "error"]
    email: str | None = None  # аккаунт Google, если подключён
    error: str | None = None  # текст для пользователя: «Доступ к Google Календарю отозван — …»
    pending: int = 0  # сколько записей ждут отправки в Google


class GoogleConnectResponse(BaseModel):
    auth_url: str  # интерфейс переходит по ссылке на страницу согласия Google
