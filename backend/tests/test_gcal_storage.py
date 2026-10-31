"""Google Календарь, шаг «хранение» (calendar-01): настройки, шифрование токена, таблицы."""

from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import models
from gcal.config import CALENDAR_SCOPE, google_config
from gcal.crypto import TokenKeyError, decrypt_token, encrypt_token

GOOGLE_ENV = {
    "GOOGLE_CLIENT_ID": "id.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "secret",
    "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/calendar/google/callback",
}


# --- настройки ------------------------------------------------------------------------------

def test_config_needs_every_variable(monkeypatch) -> None:
    for name, value in GOOGLE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GOOGLE_TOKEN_KEY", "")
    assert google_config() is None  # без ключа шифрования подключение выключено

    monkeypatch.setenv("GOOGLE_TOKEN_KEY", Fernet.generate_key().decode())
    config = google_config()
    assert config is not None and config.client_id == GOOGLE_ENV["GOOGLE_CLIENT_ID"]


def test_scope_is_the_non_sensitive_one() -> None:
    # calendar.events — чувствительное: с ним жюри увидело бы «приложение не проверено».
    assert CALENDAR_SCOPE.endswith("/calendar.app.created")


# --- шифрование -----------------------------------------------------------------------------

def test_token_roundtrip_and_not_stored_in_plain_text() -> None:
    key = Fernet.generate_key().decode()
    encrypted = encrypt_token("1//refresh-token", key)
    assert "refresh-token" not in encrypted
    assert decrypt_token(encrypted, key) == "1//refresh-token"


def test_wrong_or_bad_key_is_a_clear_error() -> None:
    encrypted = encrypt_token("token", Fernet.generate_key().decode())
    with pytest.raises(TokenKeyError):
        decrypt_token(encrypted, Fernet.generate_key().decode())
    with pytest.raises(TokenKeyError):
        encrypt_token("token", "не-ключ")


# --- таблицы (тестовая PostgreSQL) ----------------------------------------------------------

def _account(db: Session) -> models.User:
    user = models.User(id=uuid4(), login=f"u{uuid4().hex[:8]}", password_hash="x")
    db.add(user)
    db.flush()
    return user


def test_connection_belongs_to_account_and_goes_with_it(db: Session) -> None:
    user = _account(db)
    db.add(models.GoogleConnection(user_id=user.id, email="a@gmail.com", refresh_token="enc"))
    db.flush()
    connection = db.get(models.GoogleConnection, user.id)
    assert connection.status == "connected" and connection.calendar_id is None

    db.delete(user)
    db.flush()
    db.expire_all()
    assert db.scalar(select(models.GoogleConnection).where(
        models.GoogleConnection.user_id == user.id)) is None


def test_connection_status_is_checked(db: Session) -> None:
    user = _account(db)
    db.add(models.GoogleConnection(user_id=user.id, refresh_token="enc", status="broken"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_record_sync_state_values(db: Session) -> None:
    row = models.Record(user_id=uuid4(), type="task", title="Отчёт", all_day=False)
    db.add(row)
    db.flush()
    assert row.google_sync is None
    row.google_sync = "pending"
    db.flush()
    row.google_sync = "lost"
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
