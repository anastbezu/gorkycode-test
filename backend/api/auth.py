"""Учётки и вход: `/api/auth/*` (контракт docs/contracts/api.md, «Учётки и вход»).

Ошибки — статус и `{"detail": "<текст для пользователя>"}`: 401, 409, 422, 429.
Пароль и токен не попадают в лог и в тексты ошибок.
"""

import time
from collections import deque
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from db import get_session
from schemas import Account, AuthResponse, Credentials
from services.accounts import (
    LoginTakenError,
    account_view,
    authenticate,
    issue_token,
    register,
    revoke_token,
    user_by_token,
)
from stt.rate_limit import RateLimiter

from .deps import TOKEN_INVALID, bearer_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Подбор пароля: не больше 10 неудачных попыток входа за 15 минут на пару «логин + IP» — дальше
# 429. Только по логину нельзя: чужой человек десятью неверными паролями закрыл бы вход в учётку
# жюри прямо во время показа. IP — из `X-Real-IP`, который ставит Nginx на сервере (клиент его
# не подделает: бэкенд доступен только через Nginx); без Nginx — адрес соединения.
# Удачный вход счётчик сбрасывает.
FAILED_LOGIN_LIMIT = 10
FAILED_LOGIN_WINDOW_SECONDS = 15 * 60
# Предел на вход и регистрацию с одного IP: хеш пароля нарочно медленный, поток таких запросов
# занял бы единственное ядро сервера, а массовая регистрация засоряла бы базу. Не на всех
# вместе: общий счётчик дал бы любому, кто шлёт 100 запросов в минуту, закрыть вход всем —
# и жюри во время показа.
AUTH_REQUESTS_PER_MINUTE = 30

WRONG_CREDENTIALS = "Неверный логин или пароль."
LOGIN_RULES = "Логин — от 3 до 32 символов: латинские буквы, цифры, «_», «.» и «-»."
PASSWORD_RULES = "Пароль — от 8 до 128 символов."


class FailedLogins:
    """Неудачные попытки входа по ключу (логину) в скользящем окне — в памяти процесса."""

    def __init__(
        self, limit: int, window: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._fails: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        now = self._clock()
        fails = self._fails.get(key, deque())
        while fails and fails[0] <= now - self.window:
            fails.popleft()
        if not fails:
            self._fails.pop(key, None)
        return fails

    def retry_after(self, key: str) -> float | None:
        """`None` — можно пробовать; число — через сколько секунд."""
        fails = self._recent(key)
        if len(fails) < self.limit:
            return None
        return max(fails[0] + self.window - self._clock(), 0.0)

    def fail(self, key: str) -> None:
        self._fails.setdefault(key, deque()).append(self._clock())
        if len(self._fails) > 10_000:  # не даём словарю расти бесконечно
            for stale in [k for k in self._fails if not self._recent(k)]:
                self._fails.pop(stale, None)

    def clear(self, key: str) -> None:
        self._fails.pop(key, None)

    def reset(self) -> None:
        self._fails.clear()


failed_logins = FailedLogins(FAILED_LOGIN_LIMIT, FAILED_LOGIN_WINDOW_SECONDS)
auth_rate_limiter = RateLimiter(AUTH_REQUESTS_PER_MINUTE, 60)


def _too_many(detail: str, retry_after: float) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(max(int(retry_after) + 1, 1))},
    )


def _check_ip_limit(request: Request) -> None:
    retry_after = auth_rate_limiter.hit(client_ip(request))
    if retry_after is not None:
        raise _too_many("Слишком много попыток входа — подождите минуту и повторите.", retry_after)


async def credentials_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 у `/api/auth/*` — одним текстом для пользователя, а не списком ошибок FastAPI.

    Остальные маршруты отвечают как раньше (стандартный обработчик FastAPI).
    """
    if not request.url.path.startswith(router.prefix + "/"):
        return await request_validation_exception_handler(request, exc)
    fields = {str(e["loc"][-1]) for e in exc.errors() if e.get("loc")}
    parts = []
    if "login" in fields:
        parts.append(LOGIN_RULES)
    if "password" in fields:
        parts.append(PASSWORD_RULES)
    detail = " ".join(parts) or "Нужны логин и пароль."
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder({"detail": detail}),
    )


def client_ip(request: Request) -> str:
    """IP клиента: `X-Real-IP` от Nginx, без него — адрес соединения."""
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "")


def _token_or_401(authorization: str | None) -> str:
    token = bearer_token(authorization)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нужен вход: передайте токен в заголовке Authorization.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=AuthResponse,
    responses={
        409: {"description": "Логин занят"},
        422: {"description": "Логин или пароль не по правилам"},
        429: {"description": "Слишком много попыток входа и регистрации"},
    },
)
def register_account(
    body: Credentials, request: Request, db: Annotated[Session, Depends(get_session)]
) -> AuthResponse:
    """Новая учётка без записей; сразу выполняется вход. Логин сравнивается без учёта регистра."""
    _check_ip_limit(request)
    try:
        user = register(db, body.login, body.password)
    except LoginTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Этот логин уже занят — выберите другой.",
        ) from exc
    token = issue_token(db, user)
    db.commit()
    return AuthResponse(token=token, account=account_view(user))


@router.post(
    "/login",
    response_model=AuthResponse,
    responses={
        401: {"description": "Неверный логин или пароль"},
        422: {"description": "Логин или пароль не по правилам"},
        429: {"description": "Слишком много попыток входа"},
    },
)
def login(
    body: Credentials, request: Request, db: Annotated[Session, Depends(get_session)]
) -> AuthResponse:
    """Вход по логину и паролю. Ошибка одна на оба случая: не подсказывает, что неверно."""
    _check_ip_limit(request)
    key = f"{body.login.lower()}|{client_ip(request)}"
    retry_after = failed_logins.retry_after(key)
    if retry_after is not None:
        minutes = max(round(retry_after / 60), 1)
        raise _too_many(
            f"Слишком много неудачных попыток входа — попробуйте через {minutes} мин.",
            retry_after,
        )
    user = authenticate(db, body.login, body.password)
    if user is None:
        failed_logins.fail(key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=WRONG_CREDENTIALS)
    failed_logins.clear(key)
    token = issue_token(db, user)
    db.commit()
    return AuthResponse(token=token, account=account_view(user))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"description": "Нет токена или он недействителен"}},
)
def logout(
    db: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Выход: токен удаляется и больше не принимается."""
    token = _token_or_401(authorization)
    if user_by_token(db, token) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=TOKEN_INVALID,
            headers={"WWW-Authenticate": "Bearer"},
        )
    revoke_token(db, token)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=Account,
    responses={401: {"description": "Нет токена или он недействителен"}},
)
def me(
    db: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> Account:
    """Учётка по сохранённому токену — интерфейс проверяет его при открытии страницы."""
    user = user_by_token(db, _token_or_401(authorization))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=TOKEN_INVALID,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return account_view(user)
