"""Google Календарь, шаг «подключение» (calendar-01): маршруты /api/calendar/google.

Google подменён: `gcal.google.http_client` отдаёт клиента с MockTransport — сети нет.
Маршруты и база настоящие (тестовая PostgreSQL).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from api.auth import auth_rate_limiter, failed_logins
from db import get_session, models
from gcal import google
from gcal.crypto import decrypt_token
from gcal.state import make_state, read_state
from main import app
from tests.gcal_fake import FakeGoogle

pytestmark = pytest.mark.anyio
PASSWORD = "correct-horse-1"
KEY = Fernet.generate_key().decode()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def google_env(monkeypatch) -> None:
    failed_logins.reset()
    auth_rate_limiter.reset()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://test/api/calendar/google/callback")
    monkeypatch.setenv("GOOGLE_TOKEN_KEY", KEY)
    monkeypatch.setenv("GOOGLE_RETURN_URL", "http://localhost:5173/")


@pytest.fixture
def fake_google(monkeypatch) -> FakeGoogle:
    fake = FakeGoogle()
    monkeypatch.setattr(google, "http_client", fake.client)
    return fake


@pytest.fixture
async def client(db: Session) -> AsyncIterator[httpx.AsyncClient]:
    app.dependency_overrides[get_session] = lambda: db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


async def _account(client: httpx.AsyncClient) -> tuple[dict[str, str], UUID]:
    login = f"u{uuid4().hex[:10]}"
    response = await client.post("/api/auth/register", json={"login": login, "password": PASSWORD})
    assert response.status_code == 201, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['token']}"}, UUID(body["account"]["id"])


async def _connect(client, headers, fake) -> httpx.Response:
    auth_url = (await client.post("/api/calendar/google/connect", headers=headers)).json()[
        "auth_url"]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    return await client.get("/api/calendar/google/callback",
                            params={"code": "4/code", "state": state})


# --- доступ ---------------------------------------------------------------------------------

async def test_guest_gets_403_and_missing_keys_503(client, monkeypatch) -> None:
    response = await client.get("/api/calendar/google")
    assert response.status_code == 403  # гость (X-User-Id выдан сервером)
    headers, _ = await _account(client)
    monkeypatch.setenv("GOOGLE_TOKEN_KEY", "")
    assert (await client.get("/api/calendar/google", headers=headers)).status_code == 503


async def test_not_connected_status(client) -> None:
    headers, _ = await _account(client)
    response = await client.get("/api/calendar/google", headers=headers)
    assert response.json() == {"state": "not_connected", "email": None, "error": None,
                               "pending": 0}


# --- подключение ----------------------------------------------------------------------------

async def test_connect_url_asks_only_for_app_calendar_offline(client, fake_google) -> None:
    headers, user_id = await _account(client)
    auth_url = (await client.post("/api/calendar/google/connect", headers=headers)).json()[
        "auth_url"]
    query = parse_qs(urlparse(auth_url).query)
    assert query["scope"][0].split() == [
        "https://www.googleapis.com/auth/calendar.app.created", "openid", "email"]
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["redirect_uri"] == ["http://test/api/calendar/google/callback"]
    assert read_state(query["state"][0], KEY, datetime.now(UTC)) == (user_id, "Europe/Moscow")
    assert fake_google.requests == []  # до согласия в Google не ходим


async def test_callback_saves_encrypted_token_and_creates_calendar(
        client, fake_google, db: Session) -> None:
    headers, user_id = await _account(client)
    response = await _connect(client, headers, fake_google)
    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173/?calendar=connected"

    row = db.get(models.GoogleConnection, user_id)
    assert row.email == "anna@gmail.com"
    assert row.calendar_id == "cal1@group.calendar.google.com"
    assert "refresh" not in row.refresh_token  # в базе — только зашифрованный
    assert decrypt_token(row.refresh_token, KEY) == "1//refresh"
    token_request = fake_google.requests[0]
    assert fake_google.paths()[:2] == ["/token", "/calendar/v3/calendars"]
    assert b"client_secret=secret" in token_request.content  # секрет — только сервер → Google

    status = (await client.get("/api/calendar/google", headers=headers)).json()
    assert status == {"state": "connected", "email": "anna@gmail.com", "error": None,
                      "pending": 0}


async def test_reconnect_keeps_the_same_calendar(client, fake_google, db: Session) -> None:
    headers, user_id = await _account(client)
    await _connect(client, headers, fake_google)
    await _connect(client, headers, fake_google)
    assert len(fake_google.calendars) == 1
    assert db.get(models.GoogleConnection, user_id).calendar_id.startswith("cal1")


@pytest.mark.parametrize("case", ["denied", "bad_state", "expired_state", "no_refresh",
                                  "google_error"])
async def test_failed_callback_returns_error_and_saves_nothing(
        client, fake_google, db: Session, case) -> None:
    headers, user_id = await _account(client)
    params = {"code": "4/code", "state": make_state(user_id, KEY, datetime.now(UTC))}
    if case == "denied":
        params = {"error": "access_denied", "state": params["state"]}
    elif case == "bad_state":
        params["state"] = make_state(user_id, Fernet.generate_key().decode(), datetime.now(UTC))
    elif case == "expired_state":
        params["state"] = make_state(user_id, KEY, datetime.now(UTC) - timedelta(hours=1))
    elif case == "no_refresh":
        fake_google.refresh_token = None
    else:
        fake_google.token_status = 500

    response = await client.get("/api/calendar/google/callback", params=params)
    assert response.status_code == 303
    assert response.headers["location"].endswith("?calendar=error")
    assert db.get(models.GoogleConnection, user_id) is None


async def test_calendar_box_left_unchecked_returns_no_access(
        client, fake_google, db: Session) -> None:
    headers, user_id = await _account(client)
    fake_google.scopes = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
    response = await _connect(client, headers, fake_google)
    assert response.headers["location"] == "http://localhost:5173/?calendar=no_access"
    assert db.get(models.GoogleConnection, user_id) is None
    assert fake_google.calendars == []  # календарь не создавали
    assert fake_google.paths() == ["/token", "/revoke"]  # частичный доступ сразу отозван


async def test_state_of_guest_is_not_accepted(client, fake_google, db: Session) -> None:
    guest = uuid4()
    db.add(models.User(id=guest))
    db.flush()
    response = await client.get("/api/calendar/google/callback", params={
        "code": "4/code", "state": make_state(guest, KEY, datetime.now(UTC))})
    assert response.headers["location"].endswith("?calendar=error")


# --- отключение -----------------------------------------------------------------------------

async def test_disconnect_revokes_and_forgets_token(client, fake_google, db: Session) -> None:
    headers, user_id = await _account(client)
    await _connect(client, headers, fake_google)
    record = models.Record(user_id=user_id, type="task", title="Отчёт", all_day=False,
                           google_sync="pending")
    db.add(record)
    db.flush()
    assert (await client.get("/api/calendar/google", headers=headers)).json()["pending"] == 1

    response = await client.delete("/api/calendar/google", headers=headers)
    assert response.status_code == 204
    assert fake_google.paths()[-1] == "/revoke"
    assert b"token=1%2F%2Frefresh" in fake_google.requests[-1].content
    db.expire_all()
    row = db.get(models.GoogleConnection, user_id)
    assert row.status == "disconnected" and row.refresh_token is None and row.email is None
    assert row.calendar_id.startswith("cal1")  # календарь помним — для повторного подключения
    assert db.get(models.Record, record.id).google_sync is None
    status = (await client.get("/api/calendar/google", headers=headers)).json()
    assert status == {"state": "not_connected", "email": None, "error": None, "pending": 0}


async def test_reconnect_after_disconnect_writes_to_the_same_calendar(
        client, fake_google, db: Session) -> None:
    headers, user_id = await _account(client)
    await _connect(client, headers, fake_google)
    await client.delete("/api/calendar/google", headers=headers)
    response = await _connect(client, headers, fake_google)
    assert response.headers["location"].endswith("calendar=connected")
    assert len(fake_google.calendars) == 1  # второго «Голосового ассистента» нет
    db.expire_all()
    row = db.get(models.GoogleConnection, user_id)
    assert row.status == "connected" and row.email == "anna@gmail.com"


async def test_revoked_connection_shows_error(client, fake_google, db: Session) -> None:
    from gcal.connection import REVOKED_TEXT, mark_revoked

    headers, user_id = await _account(client)
    await _connect(client, headers, fake_google)
    mark_revoked(db, user_id)
    status = (await client.get("/api/calendar/google", headers=headers)).json()
    assert status["state"] == "error" and status["error"] == REVOKED_TEXT
