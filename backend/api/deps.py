"""Общие зависимости маршрутов: пользователь из `X-User-Id`, часовой пояс, стартовые данные."""

from dataclasses import dataclass
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from services.bootstrap import bootstrap_user_data

USER_ID_HEADER = "X-User-Id"
DEFAULT_TIMEZONE = "Europe/Moscow"


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    is_new: bool  # заголовка не было — UUID выдан этим запросом


def get_current_user_id(
    response: Response,
    x_user_id: str | None = Header(default=None, alias=USER_ID_HEADER),
) -> CurrentUser:
    """Пользователь — анонимный UUID браузера из заголовка `X-User-Id`.

    Нет заголовка, он пустой или не UUID — выдаём новый `uuid4()`. Он уходит клиенту в
    заголовке ответа `X-User-Id` (во всех ответах — фронтенду не нужно разбирать тело):
    фронтенд сохраняет его в localStorage и присылает в следующих запросах.
    """
    user_id: UUID | None = None
    if x_user_id and x_user_id.strip():
        try:
            user_id = UUID(x_user_id.strip())
        except ValueError:
            user_id = None
    is_new = user_id is None
    if user_id is None:
        user_id = uuid4()
    response.headers[USER_ID_HEADER] = str(user_id)
    return CurrentUser(id=user_id, is_new=is_new)


def parse_timezone(name: str | None) -> ZoneInfo:
    """IANA-пояс из запроса. Неизвестный пояс — 422 с понятным текстом."""
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Неизвестный часовой пояс: {name!r}. Ожидается IANA-имя, напр. Europe/Moscow.",
        ) from exc


def bootstrap_if_new(db: Session, user: CurrentUser, timezone_name: str) -> None:
    """Первый визит (UUID выдан этим запросом) — загрузить пользователю стартовый датасет.

    Вызывается из маршрута, а не из `get_current_user_id`: для импорта нужен часовой пояс,
    а он приходит по-разному — в теле `/api/chat` и в параметре `tz` у `/api/items`.
    """
    if user.is_new:
        bootstrap_user_data(db, user.id, timezone_name)
