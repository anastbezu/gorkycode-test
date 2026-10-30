"""Google Календарь, шаг «синхронизация» (calendar-01): наши записи → Google.

Через настоящий `POST /api/chat` (модель подменена сценарием) и подключение из шага 4;
Google — `tests/gcal_fake.py`, сети нет. База — тестовая PostgreSQL.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from agent import agent as agent_module
from api.auth import auth_rate_limiter, failed_logins
from db import get_session, models
from gcal import google
from gcal.sync import NOT_SENT_TEXT, event_body
from main import app
from schemas import (
    CreateRecord,
    Help,
    RecordStatus,
    RecordType,
    SetStatus,
    TargetRef,
    UndoLast,
    UpdateRecord,
)
from tests.gcal_fake import FakeGoogle

pytestmark = pytest.mark.anyio
MSK = ZoneInfo("Europe/Moscow")
PASSWORD = "correct-horse-1"


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
    monkeypatch.setenv("GOOGLE_TOKEN_KEY", Fernet.generate_key().decode())


@pytest.fixture
def fake(monkeypatch) -> FakeGoogle:
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


class Account:
    """Учётка с подключённым Google и разговором; модель отвечает заданными действиями."""

    def __init__(self, client: httpx.AsyncClient, db: Session, monkeypatch) -> None:
        self.client, self.db, self.monkeypatch = client, db, monkeypatch
        self.headers: dict[str, str] = {}
        self.id: UUID | None = None
        self.conversation_id: str | None = None

    async def register(self) -> "Account":
        login = f"u{uuid4().hex[:10]}"
        body = (await self.client.post("/api/auth/register",
                                       json={"login": login, "password": PASSWORD})).json()
        self.headers = {"Authorization": f"Bearer {body['token']}"}
        self.id = UUID(body["account"]["id"])
        return self

    async def connect(self) -> None:
        auth_url = (await self.client.post("/api/calendar/google/connect", headers=self.headers,
                                           params={"tz": "Europe/Moscow"})).json()["auth_url"]
        state = parse_qs(urlparse(auth_url).query)["state"][0]
        response = await self.client.get("/api/calendar/google/callback",
                                         params={"code": "4/code", "state": state})
        assert response.headers["location"].endswith("calendar=connected")

    async def say(self, text: str, action) -> dict:
        async def model(*args, **kwargs):
            return action

        self.monkeypatch.setattr(agent_module, "get_action", model)
        response = await self.client.post("/api/chat", headers=self.headers, json={
            "conversation_id": self.conversation_id, "text": text, "timezone": "Europe/Moscow"})
        assert response.status_code == 200, response.text
        body = response.json()
        self.conversation_id = body["conversation_id"]
        return body

    def record(self, record_id) -> models.Record:
        self.db.expire_all()
        return self.db.get(models.Record, UUID(str(record_id)))


def soon(days=1, hour=15, minute=0) -> datetime:
    now = datetime.now(MSK)
    return (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0,
                                                 microsecond=0)


@pytest.fixture
async def account(client, db, monkeypatch, fake) -> Account:
    acc = await (Account(client, db, monkeypatch)).register()
    await acc.connect()
    return acc


# --- как запись выглядит в Google -----------------------------------------------------------

def _row(**fields) -> models.Record:
    base = {"id": uuid4(), "user_id": uuid4(), "type": RecordType.TASK, "title": "Отчёт",
            "all_day": False, "status": RecordStatus.ACTIVE}
    return models.Record(**{**base, **fields})


def test_event_body_by_record_kind() -> None:
    start = soon()
    meeting = event_body(_row(type=RecordType.MEETING, title="Планёрка", start=start), MSK)
    assert meeting["start"] == {"dateTime": start.isoformat(), "timeZone": "Europe/Moscow"}
    assert meeting["end"]["dateTime"] == (start + timedelta(hours=1)).isoformat()

    reminder = event_body(_row(type=RecordType.REMINDER, start=start), MSK)
    assert reminder["end"]["dateTime"] == (start + timedelta(minutes=15)).isoformat()
    assert reminder["reminders"]["overrides"] == [{"method": "popup", "minutes": 0}]

    day = start.replace(hour=0).astimezone(UTC)  # «на весь день» хранится как полночь
    all_day = event_body(_row(start=day, all_day=True), MSK)
    assert all_day["start"] == {"date": start.date().isoformat()}

    deadline = event_body(_row(deadline=start.replace(hour=23, minute=59)), MSK)
    assert deadline["summary"] == "Срок: Отчёт" and "date" in deadline["start"]

    done = event_body(_row(start=start, status=RecordStatus.DONE), MSK)
    assert done["summary"] == "✓ Отчёт"
    assert event_body(_row(), MSK) is None  # без даты — в Google не уходит


# --- создание, перенос, отмена, «верни», выполнено ------------------------------------------

async def test_create_move_cancel_undo_done_reach_google(account, fake) -> None:
    start = soon()
    body = await account.say("Поставь встречу с командой завтра в 15", CreateRecord(
        type="meeting", title="встреча с командой", start=start, time_given=True))
    record_id = body["result"]["records"][0]["id"]
    event_id = UUID(record_id).hex
    assert fake.live()[event_id]["summary"] == "встреча с командой"
    assert account.record(record_id).google_sync == "synced"
    assert NOT_SENT_TEXT not in body["reply"]

    await account.say("Сдвинь её на час позже",
                      UpdateRecord(target=TargetRef(focus=True), shift_minutes=60))
    assert fake.live()[event_id]["start"]["dateTime"] == (start + timedelta(hours=1)).isoformat()

    await account.say("Отмени её", SetStatus(target=TargetRef(focus=True), status="cancelled"))
    assert event_id not in fake.live()

    await account.say("Верни", UndoLast())
    assert fake.live()[event_id]["status"] == "confirmed"  # то же событие, без дубля

    await account.say("Выполнено", SetStatus(target=TargetRef(focus=True), status="done"))
    assert fake.live()[event_id]["summary"] == "✓ встреча с командой"
    assert len(fake.events) == 1


async def test_undated_task_does_not_go_to_google(account, fake) -> None:
    body = await account.say("Запиши купить хлеб",
                             CreateRecord(type="task", title="купить хлеб", time_given=False))
    assert fake.events == {}
    assert account.record(body["result"]["records"][0]["id"]).google_sync is None


# --- сбой Google не ломает ассистента -------------------------------------------------------

async def test_google_down_keeps_record_and_catches_up_later(account, fake) -> None:
    fake.down = True
    body = await account.say("Напомни завтра в 10 позвонить маме", CreateRecord(
        type="reminder", title="позвонить маме", start=soon(hour=10), time_given=True))
    record_id = body["result"]["records"][0]["id"]
    assert body["result"]["ok"] is True  # у нас запись сохранена
    assert body["reply"].endswith(NOT_SENT_TEXT)
    assert account.record(record_id).google_sync == "pending"
    status = (await account.client.get("/api/calendar/google", headers=account.headers)).json()
    assert status["state"] == "connected" and status["pending"] == 1

    fake.down = False
    await account.say("Что ты умеешь?", Help(kind="help"))
    assert UUID(record_id).hex in fake.live()  # догнала при следующем запросе
    assert account.record(record_id).google_sync == "synced"


async def test_revoked_access_marks_error_and_assistant_still_works(account, fake) -> None:
    fake.token_status = 400  # invalid_grant: доступ отозван в Google
    body = await account.say("Поставь встречу завтра в 12", CreateRecord(
        type="meeting", title="встреча", start=soon(hour=12), time_given=True))
    assert body["result"]["ok"] is True
    assert body["reply"].endswith(NOT_SENT_TEXT)
    status = (await account.client.get("/api/calendar/google", headers=account.headers)).json()
    assert status["state"] == "error" and "переподключите" in status["error"]


async def test_deleted_calendar_is_created_again(account, fake) -> None:
    fake.calendars.clear()  # пользователь удалил «Голосовой ассистент» в Google
    body = await account.say("Поставь встречу завтра в 12", CreateRecord(
        type="meeting", title="встреча", start=soon(hour=12), time_given=True))
    assert len(fake.calendars) == 1
    assert UUID(body["result"]["records"][0]["id"]).hex in fake.live()


async def test_no_connection_means_no_google_at_all(client, db, monkeypatch, fake) -> None:
    acc = await (Account(client, db, monkeypatch)).register()  # учётка без подключения
    body = await acc.say("Поставь встречу завтра в 12", CreateRecord(
        type="meeting", title="встреча", start=soon(hour=12), time_given=True))
    assert fake.requests == [] and NOT_SENT_TEXT not in body["reply"]


# --- первая выгрузка при подключении --------------------------------------------------------

async def test_first_upload_takes_only_next_two_weeks(client, db, monkeypatch, fake) -> None:
    acc = await (Account(client, db, monkeypatch)).register()
    near = models.Record(user_id=acc.id, type="meeting", title="Скоро", start=soon(days=3),
                         all_day=False)
    far = models.Record(user_id=acc.id, type="meeting", title="Потом", start=soon(days=40),
                        all_day=False)
    past = models.Record(user_id=acc.id, type="meeting", title="Было", start=soon(days=-5),
                         all_day=False)
    db.add_all([near, far, past])
    db.flush()

    await acc.connect()
    assert set(fake.live()) == {near.id.hex}
    assert acc.record(far.id).google_sync is None


async def test_disconnected_account_is_not_synced(account, fake) -> None:
    await account.client.delete("/api/calendar/google", headers=account.headers)
    calls = len(fake.requests)
    body = await account.say("Поставь встречу завтра в 12", CreateRecord(
        type="meeting", title="встреча", start=soon(hour=12), time_given=True))
    assert len(fake.requests) == calls and NOT_SENT_TEXT not in body["reply"]
    assert account.record(body["result"]["records"][0]["id"]).google_sync is None


# --- кнопки «Моих дел» (backend-05) -----------------------------------------------------------

async def test_item_buttons_reach_google(account, fake) -> None:
    start = soon(hour=11)
    created = await account.client.post(
        "/api/items", params={"tz": "Europe/Moscow"}, headers=account.headers,
        json={"type": "meeting", "title": "Встреча с Анной", "start": start.isoformat()})
    assert created.status_code == 201, created.text
    record_id = created.json()["records"][0]["id"]
    event_id = UUID(record_id).hex
    assert fake.live()[event_id]["summary"] == "Встреча с Анной"

    moved = await account.client.patch(
        f"/api/items/{record_id}", params={"tz": "Europe/Moscow"}, headers=account.headers,
        json={"start": (start + timedelta(hours=2)).isoformat()})
    assert moved.status_code == 200, moved.text
    assert fake.live()[event_id]["start"]["dateTime"] == (start + timedelta(hours=2)).isoformat()

    for value, expected in [("cancelled", False), ("active", True)]:
        response = await account.client.post(
            f"/api/items/{record_id}/status", params={"tz": "Europe/Moscow"},
            headers=account.headers, json={"status": value})
        assert response.status_code == 200, response.text
        assert (event_id in fake.live()) is expected  # «Удалить» и «Вернуть»
    assert account.record(record_id).google_sync == "synced"


async def test_item_button_with_google_down_still_saves(account, fake) -> None:
    fake.down = True
    created = await account.client.post(
        "/api/items", params={"tz": "Europe/Moscow"}, headers=account.headers,
        json={"type": "meeting", "title": "Встреча", "start": soon(hour=12).isoformat()})
    assert created.status_code == 201
    assert account.record(created.json()["records"][0]["id"]).google_sync == "pending"
