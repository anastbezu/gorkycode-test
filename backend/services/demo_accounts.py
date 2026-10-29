"""Демо-учётки с датасетом: для жюри и для команды (backend-04).

Список — переменная окружения `DEMO_ACCOUNTS`, JSON-объект «логин → пароль»:

    DEMO_ACCOUNTS='{"jury": "пароль-жюри", "denis": "пароль-дениса"}'

- `ensure_demo_accounts` — создаёт недостающие с копией датасета (1000 записей). Вызывается
  при старте бэкенда (`main.py`), то есть сама на сервере и при локальном запуске. У уже
  созданной демо-учётки обновляет пароль, если его поменяли в `.env`.
- `reset_demo_account` — возвращает учётку к исходному датасету: удаляет её записи и
  разговоры и загружает датасет заново. Только командой на сервере
  (`python -m scripts.demo_accounts --reset <логин>`), через API — нет: пароль жюри публичный.

Датасет загружается в поясе Europe/Moscow: время в CSV — местное время пользователя.
"""

import json
import logging
import os
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from db import models
from schemas import Credentials

from .accounts import find_account, hash_password, register, verify_password
from .bootstrap import bootstrap_user_data

log = logging.getLogger(__name__)

DEMO_ACCOUNTS_ENV = "DEMO_ACCOUNTS"
DEMO_TIMEZONE = "Europe/Moscow"


class DemoAccountsError(ValueError):
    """`DEMO_ACCOUNTS` записан неправильно: текст называет, что именно."""


@dataclass(frozen=True)
class EnsureResult:
    created: list[str]
    updated_password: list[str]
    refilled: list[str]  # демо-учётка без записей — датасет загружен заново
    skipped: list[str]  # логин занят обычной учёткой — демо-учёткой её не делаем


def parse_demo_accounts(raw: str | None = None) -> dict[str, str]:
    """`DEMO_ACCOUNTS` → {логин: пароль}. Пусто — демо-учёток нет.

    Логин и пароль — по правилам `Credentials` контракта. Ошибка — `DemoAccountsError` с
    понятным текстом: пароль в текст ошибки не попадает.
    """
    raw = os.getenv(DEMO_ACCOUNTS_ENV, "") if raw is None else raw
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DemoAccountsError(
            f"{DEMO_ACCOUNTS_ENV}: не JSON (строка {exc.lineno}, символ {exc.colno}). "
            'Нужен объект вида {"jury": "пароль", "denis": "пароль"}.'
        ) from exc
    if not isinstance(data, dict):
        raise DemoAccountsError(f'{DEMO_ACCOUNTS_ENV}: нужен объект {{"логин": "пароль", ...}}.')

    accounts: dict[str, str] = {}
    for login, password in data.items():
        if not isinstance(password, str):
            raise DemoAccountsError(f"{DEMO_ACCOUNTS_ENV}: пароль «{login}» должен быть строкой.")
        try:
            Credentials(login=login, password=password)
        except ValidationError as exc:
            fields = sorted({str(e["loc"][0]) for e in exc.errors()})
            raise DemoAccountsError(
                f"{DEMO_ACCOUNTS_ENV}: учётка «{login}» — не по правилам: {', '.join(fields)} "
                "(логин 3–32 символа: латиница, цифры, _ . -; пароль 8–128 символов)."
            ) from None
        if login.lower() in {known.lower() for known in accounts}:
            raise DemoAccountsError(f"{DEMO_ACCOUNTS_ENV}: логин «{login}» повторяется.")
        accounts[login] = password
    return accounts


def ensure_demo_accounts(db: Session, accounts: dict[str, str]) -> EnsureResult:
    """Создать недостающие демо-учётки с датасетом. Повторный вызов ничего не дублирует.

    Демо-учётка без записей получает датасет заново: учётка коммитится раньше датасета, и если
    загрузка упала, следующий старт её дозаполнит, а не оставит пустой до ручного сброса.
    """
    created, updated, refilled, skipped = [], [], [], []
    for login, password in accounts.items():
        user = find_account(db, login)
        if user is None:
            user = register(db, login, password, demo=True)
            db.commit()
            bootstrap_user_data(db, user.id, DEMO_TIMEZONE)  # коммитит сам
            created.append(login)
            continue
        if not user.is_demo:
            log.warning("Демо-учётка «%s» не создана: логин занят обычной учёткой.", login)
            skipped.append(login)
            continue
        if not verify_password(user.password_hash or "", password):
            user.password_hash = hash_password(password)
            db.commit()
            updated.append(login)
        if not _has_records(db, user.id):
            bootstrap_user_data(db, user.id, DEMO_TIMEZONE)  # коммитит сам
            refilled.append(login)
    return EnsureResult(created, updated, refilled, skipped)


def _has_records(db: Session, user_id: UUID) -> bool:
    count = db.scalar(
        select(func.count()).select_from(models.Record).where(models.Record.user_id == user_id)
    )
    return bool(count)


def reset_demo_account(db: Session, login: str) -> int:
    """Вернуть демо-учётку к исходному датасету. Возвращает число загруженных записей.

    Удаляет её записи и разговоры; вход (токены) не трогает — жюри не выкидывает из учётки.
    Обычную учётку сбросить нельзя — `DemoAccountsError`.
    """
    user = find_account(db, login)
    if user is None or not user.is_demo:
        raise DemoAccountsError(f"Демо-учётки «{login}» нет.")
    db.execute(delete(models.ConversationState).where(models.ConversationState.user_id == user.id))
    db.execute(delete(models.Record).where(models.Record.user_id == user.id))
    db.commit()
    return bootstrap_user_data(db, user.id, DEMO_TIMEZONE)


def demo_logins(db: Session) -> list[str]:
    """Логины всех демо-учёток в базе — для сброса всех сразу."""
    rows = db.query(models.User.login).filter(models.User.is_demo.is_(True)).all()
    return sorted(login for (login,) in rows if login)
