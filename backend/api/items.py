"""`/api/items` — записи для панели «Мои дела» и кнопки в карточке (контракт docs/contracts/api.md).

- `GET /api/items` — записи за период.
- `POST /api/items`, `PATCH /api/items/{id}`, `POST /api/items/{id}/status` — создать, изменить,
  сменить статус кнопкой, без LLM («Записи из интерфейса», backend-05). Те же сервисы и проверки,
  что у действий агента; один запрос — одна транзакция.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from db import get_session
from schemas import (
    ActionResult,
    CreateItem,
    CreateRecord,
    ListRecords,
    Record,
    RecordType,
    SetItemStatus,
    TargetRef,
    UpdateItem,
    UpdateRecord,
)
from services import (
    create_record,
    forget_last_action_for_record,
    list_records_for_period,
    list_undated_records,
    set_status,
    update_record,
)
from services.records import get_record

from .deps import CurrentUser, get_current_user_id, parse_timezone

router = APIRouter(prefix="/api", tags=["items"])

TzQuery = Annotated[
    str | None,
    Query(description="IANA-пояс пользователя, напр. Europe/Moscow: даты ответа — в нём"),
]
NOT_FOUND = "Запись не найдена."

# Коды ответов кнопок для /docs.
CHANGE_RESPONSES = {
    400: {"description": "Заголовок X-User-Id не UUID"},
    401: {"description": "Токен учётки недействителен"},
    422: {
        "description": "Тело не по схеме или проверка не прошла: дата в прошлом, конец раньше "
        "начала, встреча без начала, дубль, нечего менять — `detail` одной строкой текста"
    },
}


def _to_local(record: Record, tz: ZoneInfo) -> Record:
    """Даты записи — в поясе пользователя (тот же момент времени, другое смещение)."""
    fields = ("start", "end", "deadline", "created_at")
    return record.model_copy(
        update={f: getattr(record, f).astimezone(tz) for f in fields if getattr(record, f)}
    )


@router.get(
    "/items",
    response_model=list[Record],
    responses={
        400: {"description": "Заголовок X-User-Id не UUID"},
        401: {"description": "Токен учётки недействителен"},
        422: {"description": "Неверные параметры или неизвестный часовой пояс"},
    },
)
def list_items(
    user: Annotated[CurrentUser, Depends(get_current_user_id)],
    db: Annotated[Session, Depends(get_session)],
    date_from: Annotated[
        AwareDatetime,
        Query(alias="from", description="Обязательно. Начало периода, ISO 8601 со смещением"),
    ],
    date_to: Annotated[
        AwareDatetime,
        Query(
            alias="to",
            description="Обязательно. Конец периода, не включается, ISO 8601 со смещением",
        ),
    ],
    type: Annotated[  # noqa: A002 — имя параметра из контракта
        list[RecordType] | None, Query(description="Фильтр по типу, можно несколько")
    ] = None,
    tz: Annotated[
        str | None, Query(description="IANA-пояс пользователя, напр. Europe/Moscow")
    ] = None,
    include_undated: Annotated[
        bool,
        Query(
            description="Добавить в конец активные записи без даты (блок «Без срока»). "
            "По умолчанию false — только записи за период, как в контракте."
        ),
    ] = False,
) -> list[Record]:
    """Записи пользователя за период `[from, to)` по началу или сроку, отсортированные по времени.

    `from` и `to` обязательны — как `date_from` / `date_to` у действия `ListRecords`
    в контракте agent-tools.md; без них — 422.
    `include_undated=true` — в конец добавляются активные записи без даты (у них `start` и
    `deadline` пустые — так фронтенд отличает их для блока «Без срока»).
    Даты в ответе — в поясе `tz` (по умолчанию Europe/Moscow).
    Синхронный маршрут: FastAPI выполняет его в пуле потоков, сервер не блокируется.
    """
    zone = parse_timezone(tz)
    if date_to <= date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Параметр `to` должен быть позже `from`.",
        )
    result = list_records_for_period(
        db, user.id, ListRecords(date_from=date_from, date_to=date_to, types=type)
    )
    records = result.records
    if include_undated:
        records = records + list_undated_records(db, user.id, type)
    return [_to_local(r, zone) for r in records]


# --- кнопки: создать, изменить, сменить статус (backend-05) -------------------------------

# Тексты 422 для тела не по схеме: контракт требует `{"detail": "<текст>"}`, а не список FastAPI.
_FIELD_RULES = {
    "type": "Тип записи — task, meeting или reminder.",
    "title": "Нужно название записи.",
    "start": "Начало — дата и время ISO 8601 с часовым поясом, напр. 2026-10-22T15:00:00+03:00.",
    "end": "Конец — дата и время ISO 8601 с часовым поясом, напр. 2026-10-22T16:00:00+03:00.",
    "deadline": "Срок — дата и время ISO 8601 с часовым поясом, напр. 2026-10-22T23:59:00+03:00.",
    "time_given": "time_given — true или false.",
    "status": "Статус — active, done или cancelled.",
    "record_id": "Неверный идентификатор записи.",
}
_BODY_RULE = "Тело запроса — JSON с полями записи по контракту."


def is_item_change(method: str, path: str) -> bool:
    """Запрос кнопки записи: `POST /api/items`, `PATCH /api/items/{id}`,
    `POST /api/items/{id}/status` (не `GET` списка)."""
    return method != "GET" and (path == "/api/items" or path.startswith("/api/items/"))


def item_validation_response(exc: RequestValidationError) -> JSONResponse:
    """422 кнопки — одной строкой: что не так, по полям, в порядке ошибок."""
    parts: list[str] = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ())]
        field = next((part for part in reversed(location) if part in _FIELD_RULES), None)
        rule = _FIELD_RULES[field] if field else _BODY_RULE
        if rule not in parts:
            parts.append(rule)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": " ".join(parts) or _BODY_RULE},
    )


def _result_in_tz(result: ActionResult, tz: ZoneInfo) -> ActionResult:
    """Записи ответа — в поясе пользователя, как у `GET /api/items`."""
    return result.model_copy(
        update={
            "records": [_to_local(r, tz) for r in result.records],
            "conflicts": [_to_local(r, tz) for r in result.conflicts],
        }
    )


def _in_one_transaction(db: Session, change: Callable[[], ActionResult]) -> ActionResult:
    """Один запрос — одна транзакция: успех — `commit`, отказ сервиса (`ok=False`) — 422 с его
    текстом, любая ошибка — откат всего, что запрос успел сделать."""
    try:
        result = change()
        if not result.ok:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=result.error or "Не получилось сохранить запись.",
            )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return result


def _existing(db: Session, user_id: UUID, record_id: UUID) -> None:
    """Записи нет или она чужая — 404 (сервис ответил бы `ok=False`, а по контракту это 404)."""
    if get_record(db, user_id, record_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


@router.post(
    "/items",
    status_code=status.HTTP_201_CREATED,
    response_model=ActionResult,
    responses=CHANGE_RESPONSES,
)
def create_item(
    body: CreateItem,
    user: Annotated[CurrentUser, Depends(get_current_user_id)],
    db: Annotated[Session, Depends(get_session)],
    tz: TzQuery = None,
) -> ActionResult:
    """Создать запись кнопкой. В `records` — созданная запись, у встречи в `conflicts` —
    пересечения: запись всё равно сохраняется, интерфейс предупреждает."""
    zone = parse_timezone(tz)
    action = CreateRecord(**body.model_dump())
    result = _in_one_transaction(db, lambda: create_record(db, user.id, action))
    return _result_in_tz(result, zone)


@router.patch(
    "/items/{record_id}",
    response_model=ActionResult,
    responses={**CHANGE_RESPONSES, 404: {"description": "Записи нет или она чужая"}},
)
def update_item(
    record_id: UUID,
    body: UpdateItem,
    user: Annotated[CurrentUser, Depends(get_current_user_id)],
    db: Annotated[Session, Depends(get_session)],
    tz: TzQuery = None,
) -> ActionResult:
    """Изменить запись кнопкой: передаются только меняемые поля, `null` — «не менять».

    Перенос начала встречи без нового конца сохраняет длительность. Сбрасывает `last_action`
    разговоров, где оно касается этой записи: «верни» в чате не откатит старое изменение
    поверх ручного.
    """
    zone = parse_timezone(tz)
    _existing(db, user.id, record_id)
    # Сервис принимает действие агента; цель (`target`) ему не нужна — запись уже найдена.
    action = UpdateRecord(target=TargetRef(), **body.model_dump())

    def change() -> ActionResult:
        result = update_record(db, user.id, record_id, action).result
        if result.ok:
            forget_last_action_for_record(db, user.id, record_id)
        return result

    return _result_in_tz(_in_one_transaction(db, change), zone)


@router.post(
    "/items/{record_id}/status",
    response_model=ActionResult,
    responses={**CHANGE_RESPONSES, 404: {"description": "Записи нет или она чужая"}},
)
def set_item_status(
    record_id: UUID,
    body: SetItemStatus,
    user: Annotated[CurrentUser, Depends(get_current_user_id)],
    db: Annotated[Session, Depends(get_session)],
    tz: TzQuery = None,
) -> ActionResult:
    """«Выполнено» (`done`), «Удалить» (`cancelled`), «Вернуть» (`active`).

    Удаление мягкое: запись пропадает из `GET /api/items`, «Вернуть» возвращает её с тем же
    `id`. Насовсем её стирает только чистка через 30 дней. Сбрасывает `last_action`
    разговоров, где оно касается этой записи.
    """
    zone = parse_timezone(tz)
    _existing(db, user.id, record_id)

    def change() -> ActionResult:
        result = set_status(db, user.id, record_id, body.status).result
        if result.ok:
            forget_last_action_for_record(db, user.id, record_id)
        return result

    return _result_in_tz(_in_one_transaction(db, change), zone)
