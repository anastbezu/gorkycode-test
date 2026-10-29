"""Записи из интерфейса (backend-05): кнопки создать, изменить, выполнено, удалить и вернуть.

Маршруты работают в сессии фикстуры `db` (подмена `get_session`): всё записанное
откатывается после теста. Без базы тесты пропускаются, как остальные тесты с БД.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy.orm import Session

import api.items as items_route
from agent import agent as agent_module
from agent.agent import process_user_turn
from db import get_session, models
from main import app
from schemas import ConversationState, LastAction, RecordStatus, RecordType, UndoLast
from services import get_or_create_conversation_state, save_conversation_state
from services.accounts import touch_guest

pytestmark = pytest.mark.anyio

MSK = ZoneInfo("Europe/Moscow")
YEKT = ZoneInfo("Asia/Yekaterinburg")
PERIOD = {"from": "2000-01-01T00:00:00+03:00", "to": "2100-01-01T00:00:00+03:00"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(db: Session) -> AsyncIterator[httpx.AsyncClient]:
    app.dependency_overrides[get_session] = lambda: db
    # raise_app_exceptions=False: необработанная ошибка маршрута — ответ 500, как на сервере.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def user(db: Session) -> UUID:
    user_id = uuid4()
    touch_guest(db, user_id)
    return user_id


def headers(user_id: UUID) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def tomorrow(hour: int, minute: int = 0, tz: ZoneInfo = MSK) -> datetime:
    day = datetime.now(tz) + timedelta(days=1)
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def add(db: Session, user_id: UUID, title: str, start: datetime | None, **fields):
    row = models.Record(
        user_id=user_id,
        type=fields.pop("type", RecordType.MEETING),
        title=title,
        start=start,
        all_day=False,
        **fields,
    )
    db.add(row)
    db.commit()  # запись была до запроса: откат запроса её не трогает
    return row


async def create(client, user_id, body: dict, tz: str = "Europe/Moscow") -> httpx.Response:
    return await client.post("/api/items", params={"tz": tz}, headers=headers(user_id), json=body)


async def patch(client, user_id, record_id, body: dict, tz="Europe/Moscow") -> httpx.Response:
    return await client.patch(
        f"/api/items/{record_id}", params={"tz": tz}, headers=headers(user_id), json=body
    )


async def set_status(client, user_id, record_id, value: str) -> httpx.Response:
    return await client.post(
        f"/api/items/{record_id}/status",
        params={"tz": "Europe/Moscow"},
        headers=headers(user_id),
        json={"status": value},
    )


async def listed(client, user_id) -> list[dict]:
    response = await client.get(
        "/api/items",
        headers=headers(user_id),
        params={**PERIOD, "include_undated": "true"},
    )
    return response.json()


def assert_detail(response: httpx.Response, code: int, text: str | None = None) -> None:
    assert response.status_code == code, response.text
    detail = response.json()["detail"]
    if text is not None:
        assert detail == text


# --- создать ------------------------------------------------------------------------------


async def test_create_task_201_in_user_tz(client, user) -> None:
    start = tomorrow(10, tz=YEKT)

    response = await create(
        client,
        user,
        {"type": "task", "title": "Купить хлеб", "start": start.isoformat()},
        tz="Asia/Yekaterinburg",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["action"] == "create_record" and body["ok"] is True
    record = body["records"][0]
    assert record["title"] == "Купить хлеб"
    assert record["start"].endswith("+05:00")  # даты — в поясе tz
    assert datetime.fromisoformat(record["start"]) == start
    assert [r["id"] for r in await listed(client, user)] == [record["id"]]


async def test_create_without_date_and_all_day(client, user) -> None:
    undated = await create(client, user, {"type": "task", "title": "Подготовить смету"})
    day = tomorrow(0)
    all_day = await create(
        client,
        user,
        {
            "type": "reminder",
            "title": "Позвонить маме",
            "start": day.isoformat(),
            "time_given": False,
        },
    )

    assert undated.status_code == all_day.status_code == 201
    assert undated.json()["records"][0]["start"] is None
    assert all_day.json()["records"][0]["all_day"] is True


async def test_create_meeting_with_conflict_is_saved(client, db, user) -> None:
    busy = add(db, user, "Созвон с Альфой", tomorrow(12))

    response = await create(
        client,
        user,
        {
            "type": "meeting",
            "title": "Встреча с Анной",
            "start": tomorrow(12, 30).isoformat(),
        },
    )

    assert response.status_code == 201
    assert [c["id"] for c in response.json()["conflicts"]] == [str(busy.id)]


@pytest.mark.parametrize(
    ("body", "text"),
    [
        (
            {"type": "task", "title": "Вчера", "start": "2020-01-01T10:00:00+03:00"},
            "Дата (start) уже в прошлом — нельзя поставить запись на прошедшее время.",
        ),
        (
            {
                "type": "meeting",
                "title": "Без времени",
                "start": "2099-01-01T00:00:00+03:00",
                "time_given": False,
            },
            "Не названо время встречи.",
        ),
        (
            {"type": "meeting", "title": "Без начала"},
            "Для встречи нужно время начала.",
        ),
        (
            {
                "type": "meeting",
                "title": "Наоборот",
                "start": "2099-01-01T15:00:00+03:00",
                "end": "2099-01-01T14:00:00+03:00",
            },
            "Время окончания должно быть позже времени начала.",
        ),
    ],
)
async def test_create_rejected_by_service_422(client, user, body: dict, text: str) -> None:
    response = await create(client, user, body)

    assert_detail(response, 422, text)
    assert await listed(client, user) == []


async def test_create_duplicate_422(client, user) -> None:
    body = {"type": "meeting", "title": "Созвон", "start": tomorrow(9).isoformat()}
    assert (await create(client, user, body)).status_code == 201

    response = await create(client, user, {**body, "title": "СОЗВОН"})

    assert_detail(response, 422, "Такая запись уже есть — второй раз не создаю.")
    assert len(await listed(client, user)) == 1


TITLE_RULE = "Нужно название записи."
TYPE_RULE = "Тип записи — task, meeting или reminder."
START_RULE = "Начало — дата и время ISO 8601 с часовым поясом, напр. 2026-10-22T15:00:00+03:00."


@pytest.mark.parametrize(
    ("body", "text"),
    [
        ({"type": "task"}, TITLE_RULE),  # нет названия
        ({"type": "task", "title": ""}, TITLE_RULE),
        ({"type": "note", "title": "Неизвестный тип"}, TYPE_RULE),
        ({"type": "task", "title": "Без пояса", "start": "2099-01-01T10:00:00"}, START_RULE),
        ({"type": "note"}, f"{TYPE_RULE} {TITLE_RULE}"),  # две ошибки — одной строкой
    ],
)
async def test_create_body_not_by_schema_422_one_text(client, user, body, text) -> None:
    # Контракт: `{"detail": "<текст>"}`, а не список ошибок FastAPI.
    assert_detail(await create(client, user, body), 422, text)


async def test_create_body_not_json_422_one_text(client, user) -> None:
    response = await client.post(
        "/api/items",
        headers={**headers(user), "Content-Type": "application/json"},
        content=b"{not json",
    )
    assert_detail(response, 422, "Тело запроса — JSON с полями записи по контракту.")


async def test_patch_body_not_by_schema_and_bad_id_422_one_text(client, db, user) -> None:
    task = add(db, user, "Купить хлеб", tomorrow(10), type=RecordType.TASK)

    bad_start = await patch(client, user, task.id, {"start": "завтра"})
    bad_id = await client.patch("/api/items/abc", headers=headers(user), json={"title": "x"})

    assert_detail(bad_start, 422, START_RULE)
    assert_detail(bad_id, 422, "Неверный идентификатор записи.")


async def test_list_keeps_standard_validation_errors(client, user) -> None:
    # Список записей — не кнопка: ошибки параметров по-прежнему списком FastAPI.
    response = await client.get("/api/items", headers=headers(user))
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


# --- изменить -----------------------------------------------------------------------------


async def test_move_meeting_keeps_duration_and_reports_conflicts(client, db, user) -> None:
    meeting = add(db, user, "Встреча с Иваном", tomorrow(10), end=tomorrow(11))
    busy = add(db, user, "Созвон с Альфой", tomorrow(15))

    response = await patch(client, user, meeting.id, {"start": tomorrow(15, 30).isoformat()})

    assert response.status_code == 200
    body = response.json()
    moved = body["records"][0]
    assert moved["id"] == str(meeting.id)
    assert datetime.fromisoformat(moved["start"]) == tomorrow(15, 30)
    assert datetime.fromisoformat(moved["end"]) == tomorrow(16, 30)  # час остался часом
    assert [c["id"] for c in body["conflicts"]] == [str(busy.id)]


async def test_patch_changes_only_given_fields(client, db, user) -> None:
    task = add(db, user, "Купить хлеб", tomorrow(10), type=RecordType.TASK)

    response = await patch(client, user, task.id, {"title": "Купить хлеб и молоко"})

    assert response.status_code == 200
    record = response.json()["records"][0]
    assert record["title"] == "Купить хлеб и молоко"
    assert datetime.fromisoformat(record["start"]) == tomorrow(10)


@pytest.mark.parametrize(
    ("body", "text"),
    [
        ({}, "Не сказано, что изменить."),
        ({"title": None, "start": None}, "Не сказано, что изменить."),
        (
            {"start": "2020-01-01T10:00:00+03:00"},
            "Дата (start) уже в прошлом — нельзя поставить запись на прошедшее время.",
        ),
    ],
)
async def test_patch_rejected_422_and_nothing_changed(client, db, user, body, text) -> None:
    task = add(db, user, "Купить хлеб", tomorrow(10), type=RecordType.TASK)

    response = await patch(client, user, task.id, body)

    assert_detail(response, 422, text)
    db.refresh(task)
    assert task.start == tomorrow(10) and task.title == "Купить хлеб"


async def test_unknown_or_foreign_record_404(client, db, user) -> None:
    stranger = uuid4()
    touch_guest(db, stranger)
    foreign = add(db, stranger, "Чужая встреча", tomorrow(10))

    for record_id in (uuid4(), foreign.id):
        moved = await patch(client, user, record_id, {"title": "Моя"})
        done = await set_status(client, user, record_id, "done")
        assert_detail(moved, 404, "Запись не найдена.")
        assert_detail(done, 404, "Запись не найдена.")

    db.refresh(foreign)
    assert foreign.title == "Чужая встреча" and foreign.status == RecordStatus.ACTIVE


# --- статус -------------------------------------------------------------------------------


async def test_done_delete_and_return_same_id(client, db, user) -> None:
    task = add(db, user, "Купить хлеб", tomorrow(10), type=RecordType.TASK)

    done = await set_status(client, user, task.id, "done")
    assert done.status_code == 200
    assert done.json()["records"][0]["status"] == "done"

    deleted = await set_status(client, user, task.id, "cancelled")
    assert deleted.status_code == 200
    assert await listed(client, user) == []  # удалённая пропадает из «Моих дел»

    returned = await set_status(client, user, task.id, "active")
    assert returned.status_code == 200
    assert [r["id"] for r in await listed(client, user)] == [str(task.id)]  # тот же id


async def test_status_not_by_schema_422(client, db, user) -> None:
    task = add(db, user, "Купить хлеб", tomorrow(10), type=RecordType.TASK)
    response = await set_status(client, user, task.id, "deleted")
    assert_detail(response, 422, "Статус — active, done или cancelled.")


# --- ручная правка и чат ------------------------------------------------------------------


def _conversation(db, user_id, last: LastAction | None, **fields) -> UUID:
    conversation_id = uuid4()
    get_or_create_conversation_state(db, conversation_id, user_id)
    state = ConversationState(
        conversation_id=conversation_id, user_id=user_id, last_action=last, **fields
    )
    save_conversation_state(db, state)
    return conversation_id


def _state(db, conversation_id) -> models.ConversationState:
    row = db.get(models.ConversationState, conversation_id)
    db.refresh(row)
    return row


@pytest.mark.parametrize("button", ["move", "status"])
async def test_manual_change_forgets_only_matching_last_action(client, db, user, button) -> None:
    meeting = add(db, user, "Встреча с Иваном", tomorrow(10))
    other = add(db, user, "Созвон с Альфой", tomorrow(12))
    moved_before = {"start": tomorrow(9).isoformat()}
    touched = _conversation(
        db,
        user,
        LastAction(action="update_record", record_ids=[meeting.id], before=[moved_before]),
        shown=[meeting.id, other.id],
        focus_record_id=meeting.id,
    )
    mass = _conversation(
        db,
        user,
        LastAction(action="set_status", record_ids=[other.id, meeting.id], before=[{}, {}]),
    )
    untouched = _conversation(
        db, user, LastAction(action="update_record", record_ids=[other.id], before=[{}])
    )

    if button == "move":
        response = await patch(client, user, meeting.id, {"start": tomorrow(16).isoformat()})
    else:
        response = await set_status(client, user, meeting.id, "done")
    assert response.status_code == 200

    assert _state(db, touched).last_action is None
    assert _state(db, mass).last_action is None  # запись среди record_ids массового действия
    assert _state(db, untouched).last_action is not None
    # Номера на экране и фокус не меняются: запись та же, номер тот же.
    assert _state(db, touched).shown == [meeting.id, other.id]
    assert _state(db, touched).focus_record_id == meeting.id


async def test_undo_in_chat_after_manual_move_does_nothing(client, db, user, monkeypatch) -> None:
    """Голосом перенесли на 9:00 (last_action), кнопкой — на 16:00; «верни» не откатывает."""
    meeting = add(db, user, "Встреча с Иваном", tomorrow(9))
    conversation = _conversation(
        db,
        user,
        LastAction(
            action="update_record",
            record_ids=[meeting.id],
            before=[{"start": tomorrow(8).isoformat()}],
        ),
    )
    assert (
        await patch(client, user, meeting.id, {"start": tomorrow(16).isoformat()})
    ).status_code == 200

    async def model(*args, **kwargs):
        return UndoLast()

    monkeypatch.setattr(agent_module, "get_action", model)
    reply = (await process_user_turn(db, user, conversation, "Верни", "Europe/Moscow")).reply

    assert reply == "Нечего возвращать."
    db.refresh(meeting)
    assert meeting.start == tomorrow(16)


async def test_error_mid_request_saves_nothing(client, db, user, monkeypatch) -> None:
    meeting = add(db, user, "Встреча с Иваном", tomorrow(10))

    def broken(*args, **kwargs):
        raise RuntimeError("база упала посреди запроса")

    monkeypatch.setattr(items_route, "forget_last_action_for_record", broken)
    response = await patch(client, user, meeting.id, {"start": tomorrow(16).isoformat()})

    assert response.status_code == 500
    db.refresh(meeting)
    assert meeting.start == tomorrow(10)  # перенос откатился вместе с запросом


# --- общее --------------------------------------------------------------------------------


async def test_user_errors(client, db) -> None:
    bad_id = await client.post(
        "/api/items", headers={"X-User-Id": "not-a-uuid"}, json={"type": "task", "title": "a"}
    )
    bad_token = await client.post(
        "/api/items", headers={"Authorization": "Bearer nope"}, json={"type": "task", "title": "a"}
    )
    bad_tz = await client.post(
        "/api/items", params={"tz": "Mars/Olympus"}, json={"type": "task", "title": "a"}
    )

    assert bad_id.status_code == 400
    assert bad_token.status_code == 401
    assert bad_tz.status_code == 422


def test_docs_show_endpoints_and_codes() -> None:
    paths = app.openapi()["paths"]
    create_op = paths["/api/items"]["post"]
    assert {"201", "400", "401", "422"} <= set(create_op["responses"])
    for path, method in (
        ("/api/items/{record_id}", "patch"),
        ("/api/items/{record_id}/status", "post"),
    ):
        assert {"200", "404", "422"} <= set(paths[path][method]["responses"])
