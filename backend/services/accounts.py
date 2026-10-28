"""Пользователи: гости, учётки, пароли и токены входа (backend-04).

- Гость — строка `users` без логина. Заводится при первом запросе с `X-User-Id`.
- Учётка — логин (без учёта регистра) и пароль. Пароль хранится только хешем argon2
  (медленный хеш с солью, `argon2-cffi`); сам пароль нигде не сохраняется и не логируется.
- Токен входа — случайная строка `secrets.token_urlsafe(32)`. В базе — только её SHA-256:
  токен длинный и случайный, подобрать его по хешу нельзя, а медленный хеш нужен паролям,
  которые придумывают люди. Срок жизни — 30 дней, выход удаляет строку.

Сервисы не коммитят: коммитит вызывающий (маршрут или команда).
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import models
from schemas import Account

TOKEN_TTL = timedelta(days=30)
# Время последнего запроса гостя пишется не чаще раза в час: для чистки через 30 дней точнее
# не нужно, а запись на каждый запрос нагружала бы базу.
LAST_SEEN_STEP = timedelta(hours=1)

_hasher = PasswordHasher()


class LoginTakenError(Exception):
    """Логин уже занят (без учёта регистра)."""


@lru_cache
def _dummy_hash() -> str:
    """Хеш для проверки пароля несуществующего логина: ответ по времени не выдаёт,
    есть ли такой логин."""
    return _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _now() -> datetime:
    return datetime.now(UTC)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def account_view(user: models.User) -> Account:
    return Account(id=user.id, login=user.login or "", demo=user.is_demo)


# --- гость --------------------------------------------------------------------------------


def touch_guest(db: Session, user_id: UUID, *, now: datetime | None = None) -> models.User:
    """Строка пользователя для `X-User-Id`: новая — заводится гостем, у гостя обновляется время
    последнего запроса (не чаще раза в час). Коммитит сам, только если что-то записал: запись
    гостя не должна зависеть от того, чем закончится остальной запрос.

    Возвращает строку как есть — если это учётка, решает вызывающий.
    """
    now = now or _now()
    created = db.scalar(
        insert(models.User)
        .values(id=user_id, last_seen_at=now)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(models.User.id)
    )
    user = db.get(models.User, user_id)
    if created is None and user.login is None and user.last_seen_at < now - LAST_SEEN_STEP:
        user.last_seen_at = now
        created = user.id
    if created is not None:
        db.commit()
    return user


# --- учётки -------------------------------------------------------------------------------


def find_account(db: Session, login: str) -> models.User | None:
    return db.scalar(select(models.User).where(func.lower(models.User.login) == login.lower()))


def register(
    db: Session, login: str, password: str, *, demo: bool = False, now: datetime | None = None
) -> models.User:
    """Новая учётка без записей. Логин занят — `LoginTakenError`."""
    if find_account(db, login) is not None:
        raise LoginTakenError(login)
    user = models.User(
        id=uuid4(),
        login=login,
        password_hash=hash_password(password),
        is_demo=demo,
        last_seen_at=now or _now(),
    )
    try:
        with db.begin_nested():
            db.add(user)
            db.flush()
    except IntegrityError as exc:  # тот же логин регистрируют одновременно
        raise LoginTakenError(login) from exc
    return user


def authenticate(db: Session, login: str, password: str) -> models.User | None:
    """Учётка по логину и паролю; неверно что-то из двух — `None` (что именно — не говорим)."""
    user = find_account(db, login)
    if user is None or user.password_hash is None:
        verify_password(_dummy_hash(), password)  # то же время ответа, что у верного логина
        return None
    if not verify_password(user.password_hash, password):
        return None
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


# --- токены -------------------------------------------------------------------------------


def issue_token(db: Session, user: models.User, *, now: datetime | None = None) -> str:
    now = now or _now()
    token = secrets.token_urlsafe(32)
    db.add(
        models.AuthToken(
            token_hash=_token_digest(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + TOKEN_TTL,
        )
    )
    db.flush()
    return token


def user_by_token(db: Session, token: str, *, now: datetime | None = None) -> models.User | None:
    """Учётка по токену; неизвестный, отозванный или истёкший токен — `None`."""
    return db.scalar(
        select(models.User)
        .join(models.AuthToken, models.AuthToken.user_id == models.User.id)
        .where(
            models.AuthToken.token_hash == _token_digest(token),
            models.AuthToken.expires_at > (now or _now()),
        )
    )


def revoke_token(db: Session, token: str) -> None:
    db.execute(delete(models.AuthToken).where(models.AuthToken.token_hash == _token_digest(token)))
