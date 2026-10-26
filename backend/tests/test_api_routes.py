"""Сценарии API (backend-02b) через `httpx.AsyncClient` на тестовой базе.

Маршруты работают в сессии фикстуры `db` (подмена `get_session`): всё, что они записали,
откатывается после теста. Без базы тесты с БД пропускаются, как остальные.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_engine, get_session, models
from main import app
from schemas import CreateRecord, ListRecords, RecordType
from services import create_record, get_or_create_conversation_state

pytestmark = pytest.mark.anyio

MSK = ZoneInfo("Europe/Moscow")
YEKT = ZoneInfo("Asia/Yekaterinburg")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """В CI нет ключа LLM: подменяется только выбор действия моделью,
    маршрут, агент, сервисы и база — настоящие."""

    async def get_action(text, now, timezone_name, llm_config=None, *, context=""):
        if text.startswith("Что у меня"):
            day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return ListRecords(date_from=day, date_to=day + timedelta(days=7))
        if text.startswith("Поставь встречу"):
            start = (now + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
            return CreateRecord(
                type=RecordType.MEETING, title="встреча с Иваном", start=start, time_given=True
            )
        return CreateRecord(type=RecordType.TASK, title=text, time_given=False)

    monkeypatch.setattr("agent.agent.get_action", get_action)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def client(db: Session) -> AsyncIterator[httpx.AsyncClient]:
    app.dependency_overrides[get_session] = lambda: db
    try:
        async with _client() as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


def _count(db: Session, user_id: UUID | None = None) -> int:
    query = select(func.count()).select_from(models.Record)
    if user_id is not None:
        query = query.where(models.Record.user_id == user_id)
    return db.scalar(query)


def _tomorrow_at(hour: int, tz: ZoneInfo) -> datetime:
    return (datetime.now(tz) + timedelta(days=1)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


async def test_new_user_gets_id_header_and_dataset(client: httpx.AsyncClient, db: Session) -> None:
    response = await client.post(
        "/api/chat",
        headers={"Origin": "https://gorky.bond"},
        json={"text": "Купить хлеб", "timezone": "Europe/Moscow"},
    )

    assert response.status_code == 200
    user_id = UUID(response.headers["X-User-Id"])
    # Фронтенд на другом origin может прочитать выданный id.
    assert "x-user-id" in response.headers["access-control-expose-headers"].lower()
    assert _count(db, user_id) == 1000 + 1  # стартовый датасет + «Купить хлеб»


async def test_user_id_not_uuid_400(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/items",
        headers={"X-User-Id": "not-a-uuid"},
        params={"from": "2026-11-01T00:00:00+03:00", "to": "2026-11-02T00:00:00+03:00"},
    )

    assert response.status_code == 400


async def test_chat_saves_and_lists_in_one_conversation(
        client: httpx.AsyncClient, db: Session
) -> None:
    user_id = uuid4()  # заголовок есть — датасет не грузится, в базе только записи теста
    headers = {"X-User-Id": str(user_id)}
    meeting = _tomorrow_at(10, MSK)
    create_record(
        db,
        user_id,
        CreateRecord(type=RecordType.MEETING, title="Демо", start=meeting, time_given=True),
    )

    saved = await client.post(
        "/api/chat", headers=headers, json={"text": "Купить хлеб", "timezone": "Europe/Moscow"}
    )
    conversation_id = saved.json()["conversation_id"]
    listed = await client.post(
        "/api/chat",
        headers=headers,
        json={
            "conversation_id": conversation_id,
            "text": "Что у меня на неделе?",
            "timezone": "Europe/Moscow",
        },
    )

    assert saved.status_code == 200
    assert saved.json()["result"]["records"][0]["title"] == "Купить хлеб"
    assert _count(db, user_id) == 2
    assert listed.status_code == 200
    assert listed.json()["conversation_id"] == conversation_id
    assert listed.json()["result"]["action"] == "list_records"
    assert [r["title"] for r in listed.json()["result"]["records"]] == ["Демо"]


async def test_chat_unknown_or_foreign_conversation_404(
        client: httpx.AsyncClient, db: Session
) -> None:
    owner, stranger = uuid4(), uuid4()
    foreign = uuid4()
    get_or_create_conversation_state(db, foreign, owner)

    for conversation_id in (uuid4(), foreign):
        response = await client.post(
            "/api/chat",
            headers={"X-User-Id": str(stranger)},
            json={
                "conversation_id": str(conversation_id),
                "text": "Купить хлеб",
                "timezone": "Europe/Moscow",
            },
        )
        assert response.status_code == 404

    assert _count(db, stranger) == 0  # реплика не исполнена


@pytest.mark.parametrize("timezone", ["Mars/Olympus", ""])
async def test_chat_unknown_timezone_422(client: httpx.AsyncClient, timezone: str) -> None:
    response = await client.post(
        "/api/chat",
        headers={"X-User-Id": str(uuid4())},
        json={"text": "Купить хлеб", "timezone": timezone},
    )

    assert response.status_code == 422


async def test_rejected_request_of_new_user_loads_no_dataset(
        client: httpx.AsyncClient, db: Session
) -> None:
    before = _count(db)

    items = await client.get(
        "/api/items",
        params={"from": "2026-11-02T00:00:00+03:00", "to": "2026-11-01T00:00:00+03:00"},
    )
    chat = await client.post(
        "/api/chat",
        json={"conversation_id": str(uuid4()), "text": "Купить хлеб", "timezone": "Europe/Moscow"},
    )

    assert items.status_code == 422
    assert chat.status_code == 404
    assert _count(db) == before  # id клиент не получил — записей «ничьего» пользователя нет


async def test_items_requires_period(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/items", headers={"X-User-Id": str(uuid4())})

    assert response.status_code == 422


async def test_items_dates_in_tz_and_undated_last(client: httpx.AsyncClient, db: Session) -> None:
    user_id = uuid4()
    headers = {"X-User-Id": str(user_id)}
    start = _tomorrow_at(10, YEKT)
    create_record(
        db,
        user_id,
        CreateRecord(type=RecordType.MEETING, title="Демо", start=start, time_given=True),
    )
    create_record(
        db, user_id, CreateRecord(type=RecordType.TASK, title="Прочитать книгу", time_given=False)
    )
    day = start.replace(hour=0)
    params = {
        "from": day.isoformat(),
        "to": (day + timedelta(days=1)).isoformat(),
        "tz": "Asia/Yekaterinburg",
    }

    period = await client.get("/api/items", headers=headers, params=params)
    with_undated = await client.get(
        "/api/items", headers=headers, params={**params, "include_undated": "true"}
    )

    assert period.status_code == 200
    assert [r["title"] for r in period.json()] == ["Демо"]
    assert datetime.fromisoformat(period.json()[0]["start"]).utcoffset() == timedelta(hours=5)
    assert datetime.fromisoformat(period.json()[0]["start"]) == start  # тот же момент
    assert [r["title"] for r in with_undated.json()] == ["Демо", "Прочитать книгу"]
    assert with_undated.json()[1]["start"] is None
    assert with_undated.json()[1]["deadline"] is None


@pytest.mark.parametrize(
    ("origin", "allowed"), [("https://gorky.bond", True), ("https://evil.example", False)]
)
async def test_cors(origin: str, allowed: bool) -> None:
    # Предзапрос браузера до маршрута не доходит — база не нужна.
    async with _client() as client:
        response = await client.options(
            "/api/chat",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-user-id",
            },
        )

    assert (response.headers.get("access-control-allow-origin") == origin) is allowed


async def test_health_503_when_db_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nothing@127.0.0.1:1/nodb")
    get_engine.cache_clear()
    try:
        async with _client() as client:
            response = await client.get("/health")
    finally:
        get_engine.cache_clear()  # следующие тесты создадут движок по своему адресу

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "unavailable"}


async def test_chat_meeting_saved_with_time_and_zone(
        client: httpx.AsyncClient, db: Session
) -> None:
    user_id = uuid4()
    response = await client.post(
        "/api/chat",
        headers={"X-User-Id": str(user_id)},
        json={"text": "Поставь встречу с Иваном завтра в 15:00", "timezone": "Europe/Moscow"},
    )

    assert response.status_code == 200
    row = db.scalar(select(models.Record).where(models.Record.user_id == user_id))
    assert row.type is RecordType.MEETING
    assert row.start == _tomorrow_at(15, MSK)
    assert "15:00" in response.json()["reply"]
