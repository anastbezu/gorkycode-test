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

    - Заголовка нет или он пустой — выдаём новый `uuid4()` (новый пользователь).
    - Заголовок есть, но это не UUID — 400: это ошибка клиента, молча подменять id нельзя.
    - Корректный UUID — это и есть пользователь.

    Итоговый id уходит клиенту в заголовке ответа `X-User-Id` (во всех ответах — фронтенду
    не нужно разбирать тело): фронтенд сохраняет его в localStorage и присылает дальше.
    """
    raw = (x_user_id or "").strip()
    if not raw:
        user_id, is_new = uuid4(), True
    else:
        try:
            user_id, is_new = UUID(raw), False
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Заголовок X-User-Id должен быть UUID. "
                "Уберите его, чтобы получить новый идентификатор.",
            ) from exc
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
