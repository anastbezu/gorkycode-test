"""Google Календарь у учётки (calendar-01): состояние, подключение, возврат, отключение.

Контракт — docs/contracts/api.md, «Внешний календарь (Google)». Гость — 403, ключей Google
на сервере нет — 503.
"""

from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from db import get_session
from gcal.config import GoogleConfig, google_config
from gcal.connection import (
    ConnectError,
    connection_status,
    disconnect,
    finish_connect,
    start_connect,
)
from schemas import GoogleCalendarStatus, GoogleConnectResponse

from .deps import CurrentUser, get_current_user_id

router = APIRouter(prefix="/api/calendar/google", tags=["calendar"])

ERRORS = {
    401: {"description": "Токен учётки недействителен"},
    403: {"description": "Гость: Google Календарь подключается только у учётки"},
    503: {"description": "Подключение Google не настроено на сервере"},
}


def account(user: Annotated[CurrentUser, Depends(get_current_user_id)]) -> CurrentUser:
    if not user.is_account:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google Календарь подключается только у учётки — войдите.",
        )
    return user


def config() -> GoogleConfig:
    cfg = google_config()
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Подключение Google Календаря на сервере не настроено.",
        )
    return cfg


@router.get("", response_model=GoogleCalendarStatus, responses=ERRORS)
def get_status(
    user: Annotated[CurrentUser, Depends(account)],
    db: Annotated[Session, Depends(get_session)],
    _: Annotated[GoogleConfig, Depends(config)],
) -> GoogleCalendarStatus:
    return connection_status(db, user.id)


@router.post("/connect", response_model=GoogleConnectResponse, responses=ERRORS)
def connect(
    user: Annotated[CurrentUser, Depends(account)],
    cfg: Annotated[GoogleConfig, Depends(config)],
) -> GoogleConnectResponse:
    """Ссылка на страницу согласия Google; повторный вызов — переподключение."""
    return GoogleConnectResponse(auth_url=start_connect(cfg, user.id, datetime.now(UTC)))


def _back(cfg: GoogleConfig, result: str) -> RedirectResponse:
    sep = "&" if "?" in cfg.return_url else "?"
    url = f"{cfg.return_url}{sep}{urlencode({'calendar': result})}"
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/callback", include_in_schema=False)
def callback(
    db: Annotated[Session, Depends(get_session)],
    cfg: Annotated[GoogleConfig, Depends(config)],
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Сюда Google возвращает пользователя; учётка — из подписанного `state`, не из заголовка
    (браузер приходит обычным переходом). Пользователь отказался — `error=access_denied`."""
    if error or not code or not state:
        return _back(cfg, "error")
    try:
        finish_connect(db, cfg, code, state, datetime.now(UTC))
        db.commit()
    except ConnectError:
        db.rollback()
        return _back(cfg, "error")
    return _back(cfg, "connected")


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_connection(
    user: Annotated[CurrentUser, Depends(account)],
    db: Annotated[Session, Depends(get_session)],
    cfg: Annotated[GoogleConfig, Depends(config)],
) -> Response:
    disconnect(db, cfg, user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
