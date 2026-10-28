"""Общие зависимости маршрутов: пользователь (учётка по токену или гость по `X-User-Id`),
часовой пояс."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from db import get_session
from services.accounts import touch_guest, user_by_token

USER_ID_HEADER = "X-User-Id"
DEFAULT_TIMEZONE = "Europe/Moscow"

TOKEN_INVALID = "Вход недействителен или истёк — войдите снова."


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    is_new: bool  # гость без заголовка — UUID выдан этим запросом
    is_account: bool = False  # пользователь — учётка (вошёл по токену)


def _unauthorized(detail: str = TOKEN_INVALID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def bearer_token(authorization: str | None) -> str | None:
    """Токен из `Authorization: Bearer <token>`; заголовка нет — `None`, иной вид — 401."""
    if authorization is None or not authorization.strip():
        return None
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized()
    return token.strip()


def get_current_user_id(
    response: Response,
    db: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header(alias=USER_ID_HEADER)] = None,
) -> CurrentUser:
    """Пользователь запроса (контракт api.md, «Учётки и вход»).

    - Есть `Authorization: Bearer <token>` — это учётка; `X-User-Id` не читается и не выдаётся.
      Токен неизвестный, отозванный или истёкший — 401: в гостя молча не переводим,
      интерфейс решает сам.
    - Токена нет — гость по `X-User-Id`:
      - заголовка нет или он пустой — новый `uuid4()`, гость с пустым календарём;
      - не UUID — 400: ошибка клиента, молча подменять id нельзя;
      - id учётки без токена — 401: иначе знающий id входил бы в учётку без пароля.
      Строка гостя заводится в `users` при первом запросе; id уходит клиенту в заголовке
      ответа `X-User-Id`.
    """
    token = bearer_token(authorization)
    if token is not None:
        account = user_by_token(db, token)
        if account is None:
            raise _unauthorized()
        return CurrentUser(id=account.id, is_new=False, is_account=True)

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
    if touch_guest(db, user_id).login is not None:
        raise _unauthorized("Это идентификатор учётки — войдите по логину и паролю.")
    response.headers[USER_ID_HEADER] = str(user_id)
    return CurrentUser(id=user_id, is_new=is_new)


def parse_timezone(name: str | None) -> ZoneInfo:
    """IANA-пояс из запроса: `None` — пояс по умолчанию. Неизвестный или пустой — 422."""
    try:
        return ZoneInfo(DEFAULT_TIMEZONE if name is None else name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:  # OSError — слишком длинное имя
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Неизвестный часовой пояс: {name!r}. Ожидается IANA-имя, напр. Europe/Moscow.",
        ) from exc
