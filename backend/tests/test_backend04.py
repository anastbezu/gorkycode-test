"""Учётки и вход, гость, демо-учётки, срок хранения (backend-04).

Маршруты работают в сессии фикстуры `db` (подмена `get_session`): всё записанное
откатывается после теста. Без базы тесты пропускаются, как остальные тесты с БД.
"""

import asyncio
import hashlib
import logging
import struct
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import api.stt as stt_route
import main
from api.auth import auth_rate_limiter, failed_logins
from db import get_session, models
from main import app
from schemas import CreateRecord, ListRecords, RecordStatus, RecordType
from services import (
    create_record,
    get_or_create_conversation_state,
    list_records_for_period,
    set_status,
)
from services.accounts import issue_token, register, touch_guest
from services.demo_accounts import (
    DemoAccountsError,
    ensure_demo_accounts,
    parse_demo_accounts,
    reset_demo_account,
)
from services.retention import cleanup

pytestmark = pytest.mark.anyio

MSK = ZoneInfo("Europe/Moscow")
PASSWORD = "correct-horse-1"
PERIOD = {"from": "2000-01-01T00:00:00+03:00", "to": "2100-01-01T00:00:00+03:00"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_limits() -> None:
    failed_logins.reset()
    auth_rate_limiter.reset()
    stt_route.rate_limiter.reset()
    stt_route.global_rate_limiter.reset()


@pytest.fixture
async def client(db: Session) -> AsyncIterator[httpx.AsyncClient]:
    app.dependency_overrides[get_session] = lambda: db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: httpx.AsyncClient, login: str = "anna") -> dict:
    response = await client.post("/api/auth/register", json={"login": login, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response.json()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _task(db: Session, user_id: UUID, title: str) -> UUID:
    result = create_record(
        db, user_id, CreateRecord(type=RecordType.TASK, title=title, time_given=False)
    )
    return result.records[0].id


async def _items(client: httpx.AsyncClient, headers: dict[str, str]) -> httpx.Response:
    return await client.get(
        "/api/items", headers=headers, params={**PERIOD, "include_undated": "true"}
    )


# --- регистрация, вход, выход -------------------------------------------------------------


async def test_register_creates_empty_account_and_logs_in(
    client: httpx.AsyncClient, db: Session
) -> None:
    body = await _register(client, "Anna_K")

    assert body["account"]["login"] == "Anna_K"
    assert body["account"]["demo"] is False
    account_id = UUID(body["account"]["id"])
    items = await _items(client, _bearer(body["token"]))
    assert items.status_code == 200
    assert items.json() == []  # новая учётка — без записей
    assert "X-User-Id" not in items.headers  # у учётки X-User-Id не выдаётся
    me = await client.get("/api/auth/me", headers=_bearer(body["token"]))
    assert me.json() == {"id": str(account_id), "login": "Anna_K", "demo": False}


async def test_password_and_token_are_stored_only_as_hashes(
    client: httpx.AsyncClient, db: Session
) -> None:
    body = await _register(client)

    user = db.get(models.User, UUID(body["account"]["id"]))
    assert user.password_hash.startswith("$argon2")
    assert PASSWORD not in user.password_hash
    stored = db.scalars(select(models.AuthToken.token_hash)).all()
    assert body["token"] not in stored  # в базе — только SHA-256 токена


async def test_login_taken_case_insensitive_409(client: httpx.AsyncClient) -> None:
    await _register(client, "anna")

    response = await client.post(
        "/api/auth/register", json={"login": "ANNA", "password": "another-pass-2"}
    )

    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"login": "an", "password": PASSWORD}, "Логин"),
        ({"login": "аня", "password": PASSWORD}, "Логин"),
        ({"login": "anna", "password": "short"}, "Пароль"),
        ({"login": "anna"}, "Пароль"),
    ],
)
async def test_credentials_rules_422_with_text(
    client: httpx.AsyncClient, body: dict, expected: str
) -> None:
    for path in ("/api/auth/register", "/api/auth/login"):
        response = await client.post(path, json=body)
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert isinstance(detail, str) and detail.startswith(expected)


async def test_other_routes_keep_standard_validation_errors(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/items", headers={"X-User-Id": str(uuid4())})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


async def test_login_case_insensitive_and_one_error_text(client: httpx.AsyncClient) -> None:
    await _register(client, "anna")

    ok = await client.post("/api/auth/login", json={"login": "AnNa", "password": PASSWORD})
    wrong_password = await client.post(
        "/api/auth/login", json={"login": "anna", "password": "wrong-pass-9"}
    )
    unknown_login = await client.post(
        "/api/auth/login", json={"login": "nobody", "password": PASSWORD}
    )

    assert ok.status_code == 200
    assert ok.json()["account"]["login"] == "anna"
    assert wrong_password.status_code == unknown_login.status_code == 401
    assert wrong_password.json() == unknown_login.json()  # не подсказывает, что неверно


async def test_failed_logins_limit_429(client: httpx.AsyncClient) -> None:
    await _register(client, "anna")
    await _register(client, "boris")
    wrong = {"login": "anna", "password": "wrong-pass-9"}

    for _ in range(failed_logins.limit):
        assert (await client.post("/api/auth/login", json=wrong)).status_code == 401

    limited = await client.post("/api/auth/login", json={"login": "ANNA", "password": PASSWORD})
    assert limited.status_code == 429  # и с верным паролем, пока окно не прошло
    assert int(limited.headers["Retry-After"]) > 0
    assert isinstance(limited.json()["detail"], str)
    # Лимит — на логин: другая учётка входит…
    other = await client.post("/api/auth/login", json={"login": "boris", "password": PASSWORD})
    assert other.status_code == 200
    # …а этот логин закрыт с любого адреса.
    elsewhere = await client.post(
        "/api/auth/login",
        headers={"X-Real-IP": "203.0.113.7"},
        json={"login": "anna", "password": PASSWORD},
    )
    assert elsewhere.status_code == 429


def test_failed_logins_window() -> None:
    now = [0.0]
    limiter = type(failed_logins)(2, 60, clock=lambda: now[0])
    limiter.fail("anna")
    limiter.fail("anna")
    assert limiter.retry_after("anna") == pytest.approx(60)
    now[0] = 61.0
    assert limiter.retry_after("anna") is None
    limiter.fail("anna")
    limiter.clear("anna")  # удачный вход сбрасывает счётчик
    assert limiter.retry_after("anna") is None


async def test_logout_revokes_token(client: httpx.AsyncClient) -> None:
    token = (await _register(client))["token"]

    assert (await client.post("/api/auth/logout", headers=_bearer(token))).status_code == 204
    for response in (
        await client.get("/api/auth/me", headers=_bearer(token)),
        await _items(client, _bearer(token)),
        await client.post("/api/auth/logout", headers=_bearer(token)),
    ):
        assert response.status_code == 401
        assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer"}, {"Authorization": "Basic abc"}, _bearer("not-a-token")],
)
async def test_me_without_valid_token_401(client: httpx.AsyncClient, headers: dict) -> None:
    response = await client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401


async def test_expired_token_401(client: httpx.AsyncClient, db: Session) -> None:
    user = register(db, "old_user", PASSWORD)
    token = issue_token(db, user, now=datetime.now(UTC) - timedelta(days=31))

    assert (await _items(client, _bearer(token))).status_code == 401


async def test_login_does_not_log_password_or_token(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    token = (await _register(client))["token"]
    await client.post("/api/auth/login", json={"login": "anna", "password": "wrong-pass-9"})

    assert PASSWORD not in caplog.text
    assert "wrong-pass-9" not in caplog.text
    assert token not in caplog.text


# --- учётка и гость в одном маршруте ------------------------------------------------------


async def test_token_and_guest_in_same_route(client: httpx.AsyncClient, db: Session) -> None:
    body = await _register(client)
    account_id = UUID(body["account"]["id"])
    guest_id = uuid4()
    touch_guest(db, guest_id)
    _task(db, account_id, "Задача учётки")
    _task(db, guest_id, "Задача гостя")

    as_account = await _items(client, _bearer(body["token"]))
    as_guest = await _items(client, {"X-User-Id": str(guest_id)})
    # Есть токен — это учётка, X-User-Id не читается.
    both = await _items(client, {**_bearer(body["token"]), "X-User-Id": str(guest_id)})

    assert [r["title"] for r in as_account.json()] == ["Задача учётки"]
    assert [r["title"] for r in as_guest.json()] == ["Задача гостя"]
    assert as_guest.headers["X-User-Id"] == str(guest_id)
    assert [r["title"] for r in both.json()] == ["Задача учётки"]
    assert "X-User-Id" not in both.headers


async def test_account_id_as_guest_header_401(client: httpx.AsyncClient) -> None:
    """Знающий id учётки не входит в неё без пароля через X-User-Id."""
    body = await _register(client)

    response = await _items(client, {"X-User-Id": body["account"]["id"]})

    assert response.status_code == 401


async def test_new_guest_row_and_empty_calendar(client: httpx.AsyncClient, db: Session) -> None:
    response = await _items(client, {})

    guest_id = UUID(response.headers["X-User-Id"])
    assert response.json() == []
    user = db.get(models.User, guest_id)
    assert user is not None and user.login is None


async def test_chat_with_token_and_guest_conversation_404(
    client: httpx.AsyncClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def get_action(text, now, timezone_name, llm_config=None, *, context=""):
        return CreateRecord(type=RecordType.TASK, title=text, time_given=False)

    monkeypatch.setattr("agent.agent.get_action", get_action)
    token = (await _register(client))["token"]
    guest = await client.post(
        "/api/chat", json={"text": "Купить хлеб", "timezone": "Europe/Moscow"}
    )

    as_account = await client.post(
        "/api/chat",
        headers=_bearer(token),
        json={"text": "Купить молоко", "timezone": "Europe/Moscow"},
    )
    foreign = await client.post(
        "/api/chat",
        headers=_bearer(token),
        json={
            "conversation_id": guest.json()["conversation_id"],
            "text": "Купить сыр",
            "timezone": "Europe/Moscow",
        },
    )

    assert as_account.status_code == 200
    assert [r["title"] for r in (await _items(client, _bearer(token))).json()] == ["Купить молоко"]
    assert foreign.status_code == 404  # разговор гостя к учётке не переходит


async def test_stt_with_token(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_transcribe(audio: bytes, content_type: str) -> str:
        return "Купить хлеб"

    monkeypatch.setattr(stt_route, "transcribe", fake_transcribe)
    token = (await _register(client))["token"]
    data = b"\x80" * 16000  # 2 с: 8 кГц, моно, 8 бит
    fmt = struct.pack("<HHIIHH", 1, 1, 8000, 8000, 1, 8)
    wav = (
        b"RIFF"
        + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data))
        + b"WAVEfmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )

    ok = await client.post(
        "/api/stt", headers=_bearer(token), files={"audio": ("v.wav", wav, "audio/wav")}
    )
    bad = await client.post(
        "/api/stt", headers=_bearer("nope"), files={"audio": ("v.wav", wav, "audio/wav")}
    )

    assert ok.status_code == 200 and ok.json() == {"text": "Купить хлеб"}
    assert "X-User-Id" not in ok.headers
    assert bad.status_code == 401


async def test_cors_allows_authorization_header(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/api/items",
        headers={
            "Origin": "https://gorky.bond",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_guest_last_seen_written_at_most_hourly(db: Session) -> None:
    guest_id = uuid4()
    start = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    touch_guest(db, guest_id, now=start)

    touch_guest(db, guest_id, now=start + timedelta(minutes=30))
    assert db.get(models.User, guest_id).last_seen_at == start
    touch_guest(db, guest_id, now=start + timedelta(hours=2))
    assert db.get(models.User, guest_id).last_seen_at == start + timedelta(hours=2)


# --- демо-учётки --------------------------------------------------------------------------


def _record_count(db: Session, user_id: UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(models.Record).where(models.Record.user_id == user_id)
    )


def test_parse_demo_accounts() -> None:
    assert parse_demo_accounts("") == {}
    assert parse_demo_accounts('{"jury": "jury-pass-1", "denis": "a:b,c pass"}') == {
        "jury": "jury-pass-1",
        "denis": "a:b,c pass",  # в пароле можно любые символы
    }


@pytest.mark.parametrize(
    "raw",
    [
        "jury:pass",  # не JSON
        '["jury"]',  # не объект
        '{"jury": 12345678}',  # пароль не строка
        '{"ju": "jury-pass-1"}',  # логин короче 3
        '{"jury": "short"}',  # пароль короче 8
        '{"jury": "jury-pass-1", "JURY": "jury-pass-2"}',  # логин повторяется
    ],
)
def test_parse_demo_accounts_errors(raw: str) -> None:
    with pytest.raises(DemoAccountsError) as exc:
        parse_demo_accounts(raw)
    message = str(exc.value)
    assert "DEMO_ACCOUNTS" in message
    assert "jury-pass" not in message and "12345678" not in message  # пароль в текст не попадает


def test_ensure_demo_accounts_once_with_dataset(db: Session) -> None:
    accounts = {"jury_t": "jury-pass-1", "team_t": "team-pass-1"}
    register(db, "taken_t", PASSWORD)  # обычная учётка с тем же логином, что в списке

    first = ensure_demo_accounts(db, {**accounts, "Taken_T": "demo-pass-1"})
    second = ensure_demo_accounts(db, accounts)

    assert sorted(first.created) == ["jury_t", "team_t"]
    assert first.skipped == ["Taken_T"]
    assert second.created == second.updated_password == []
    jury = db.scalar(select(models.User).where(models.User.login == "jury_t"))
    assert jury.is_demo
    assert _record_count(db, jury.id) == 1000


def test_ensure_demo_accounts_updates_changed_password(db: Session) -> None:
    ensure_demo_accounts(db, {"jury_t": "jury-pass-1"})

    result = ensure_demo_accounts(db, {"jury_t": "jury-pass-2"})

    assert result.updated_password == ["jury_t"]


async def test_demo_login_from_two_devices_sees_same_records(
    client: httpx.AsyncClient, db: Session
) -> None:
    ensure_demo_accounts(db, {"jury_t": "jury-pass-1"})
    credentials = {"login": "jury_t", "password": "jury-pass-1"}

    laptop = (await client.post("/api/auth/login", json=credentials)).json()
    phone = (await client.post("/api/auth/login", json=credentials)).json()

    assert laptop["account"]["demo"] is True
    assert laptop["token"] != phone["token"]
    first = (await _items(client, _bearer(laptop["token"]))).json()
    second = (await _items(client, _bearer(phone["token"]))).json()
    assert len(first) > 0 and first == second


def test_reset_demo_account_restores_dataset_only_for_it(db: Session) -> None:
    ensure_demo_accounts(db, {"jury_t": "jury-pass-1", "team_t": "team-pass-1"})
    jury = db.scalar(select(models.User).where(models.User.login == "jury_t"))
    team = db.scalar(select(models.User).where(models.User.login == "team_t"))
    _task(db, jury.id, "Лишняя задача")
    _task(db, team.id, "Задача команды")
    get_or_create_conversation_state(db, uuid4(), jury.id)
    token = issue_token(db, jury)
    db.commit()

    loaded = reset_demo_account(db, "JURY_T")

    assert loaded == 1000
    assert _record_count(db, jury.id) == 1000
    assert _record_count(db, team.id) == 1001  # другую учётку сброс не трогает
    assert not db.scalars(
        select(models.ConversationState).where(models.ConversationState.user_id == jury.id)
    ).all()
    assert db.get(models.AuthToken, _digest(token)) is not None  # вход жюри не сброшен


def test_reset_only_demo_accounts(db: Session) -> None:
    register(db, "anna_t", PASSWORD)
    with pytest.raises(DemoAccountsError):
        reset_demo_account(db, "anna_t")
    with pytest.raises(DemoAccountsError):
        reset_demo_account(db, "nobody_t")


# --- срок хранения ------------------------------------------------------------------------


def test_cancel_sets_and_return_clears_cancelled_at(db: Session) -> None:
    user_id = uuid4()
    record_id = _task(db, user_id, "Купить хлеб")

    set_status(db, user_id, record_id, RecordStatus.CANCELLED)
    cancelled_at = db.get(models.Record, record_id).cancelled_at
    set_status(db, user_id, record_id, RecordStatus.CANCELLED)  # повторная отмена — то же время
    assert db.get(models.Record, record_id).cancelled_at == cancelled_at
    assert cancelled_at is not None

    set_status(db, user_id, record_id, RecordStatus.ACTIVE)
    assert db.get(models.Record, record_id).cancelled_at is None


def test_cleanup_after_30_days(db: Session) -> None:
    now = datetime.now(UTC)
    old, fresh = now - timedelta(days=31), now - timedelta(days=29)

    stale_guest, fresh_guest = uuid4(), uuid4()
    touch_guest(db, stale_guest, now=old)
    touch_guest(db, fresh_guest, now=fresh)
    _task(db, stale_guest, "Старый гость")
    get_or_create_conversation_state(db, uuid4(), stale_guest)
    _task(db, fresh_guest, "Свежий гость")

    account = register(db, "sleepy_t", PASSWORD, now=old)  # учётку не трогаем никогда
    account_task = _task(db, account.id, "Задача учётки")
    old_cancel = _task(db, account.id, "Отменена давно")
    new_cancel = _task(db, account.id, "Отменена недавно")
    for record_id, when in ((old_cancel, old), (new_cancel, fresh)):
        set_status(db, account.id, record_id, RecordStatus.CANCELLED)
        db.get(models.Record, record_id).cancelled_at = when
    expired = issue_token(db, account, now=old)
    live = issue_token(db, account, now=fresh)
    db.commit()

    result = cleanup(db, now=now)

    assert result.guests == 1
    assert result.records == 1
    assert result.tokens == 1
    assert db.get(models.User, stale_guest) is None
    assert _record_count(db, stale_guest) == 0
    assert not db.scalars(
        select(models.ConversationState).where(models.ConversationState.user_id == stale_guest)
    ).all()
    assert db.get(models.User, fresh_guest) is not None
    assert db.get(models.User, account.id) is not None
    remaining = {
        r.title
        for r in db.scalars(select(models.Record).where(models.Record.user_id == account.id))
    }
    assert remaining == {"Задача учётки", "Отменена недавно"}
    assert db.get(models.Record, account_task) is not None
    assert db.get(models.AuthToken, _digest(expired)) is None
    assert db.get(models.AuthToken, _digest(live)) is not None

    # Повторный запуск ничего не находит и ничего не ломает.
    again = cleanup(db, now=now)
    assert (again.guests, again.records, again.tokens) == (0, 0, 0)


def test_list_hides_cancelled_and_cleanup_removes_it_for_good(db: Session) -> None:
    """«Вернуть» по записи, удалённой чисткой, — запись не найдена (контракт: 404)."""
    user_id = uuid4()
    touch_guest(db, user_id)
    record_id = _task(db, user_id, "Купить хлеб")
    set_status(db, user_id, record_id, RecordStatus.CANCELLED)
    db.get(models.Record, record_id).cancelled_at = datetime.now(UTC) - timedelta(days=31)
    db.commit()

    cleanup(db)

    assert set_status(db, user_id, record_id, RecordStatus.ACTIVE).result.ok is False
    listed = list_records_for_period(
        db, user_id, ListRecords(date_from=datetime(2000, 1, 1, tzinfo=MSK))
    )
    assert listed.records == []


# --- запуск бэкенда -----------------------------------------------------------------------


@pytest.fixture
def startup_session(db: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """`main` открывает сессию сам (`SessionLocal`) — подставляем сессию теста."""

    class _Same:
        def __enter__(self) -> Session:
            return db

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(main, "SessionLocal", _Same)
    return db


def test_startup_creates_demo_accounts_from_env(
    startup_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_ACCOUNTS", '{"jury_s": "jury-pass-1"}')

    main._ensure_demo_accounts()

    jury = startup_session.scalar(select(models.User).where(models.User.login == "jury_s"))
    assert jury is not None and jury.is_demo
    assert _record_count(startup_session, jury.id) == 1000


def test_startup_survives_broken_demo_accounts(
    startup_session: Session, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("DEMO_ACCOUNTS", '{"jury_s": "short"}')

    main._ensure_demo_accounts()  # ошибка — в лог, сервер всё равно стартует

    assert "DEMO_ACCOUNTS" in caplog.text
    assert "short" not in caplog.text  # пароль в лог не попадает


async def test_lifespan_runs_demo_accounts_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main, "_ensure_demo_accounts", lambda: calls.append("demo"))
    monkeypatch.setattr(main, "_cleanup_once", lambda: calls.append("cleanup"))

    async with main.lifespan(app):
        for _ in range(50):  # чистка — фоновая задача: даём ей стартовать
            if "cleanup" in calls:
                break
            await asyncio.sleep(0.01)

    assert calls == ["demo", "cleanup"]
