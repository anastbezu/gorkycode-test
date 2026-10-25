"""`GET /api/items` — записи для боковой панели «Мои дела» (контракт docs/contracts/api.md)."""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from db import get_session
from schemas import ListRecords, Record, RecordType
from services import list_records_for_period, list_undated_records

from .deps import CurrentUser, bootstrap_if_new, get_current_user_id, parse_timezone

router = APIRouter(prefix="/api", tags=["items"])

DEFAULT_PERIOD_DAYS = 7


def _to_local(record: Record, tz) -> Record:
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
        422: {"description": "Неверные параметры или неизвестный часовой пояс"},
    },
)
def list_items(
    user: CurrentUser = Depends(get_current_user_id),
    db: Session = Depends(get_session),
    date_from: Annotated[
        AwareDatetime | None,
        Query(alias="from", description="Начало периода, ISO 8601 со смещением"),
    ] = None,
    date_to: Annotated[
        AwareDatetime | None,
        Query(alias="to", description="Конец периода, не включается, ISO 8601 со смещением"),
    ] = None,
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

    Без `from` / `to` — ближайшие 7 дней с начала сегодняшнего дня в поясе `tz`.
    `include_undated=true` — в конец добавляются активные записи без даты (у них `start` и
    `deadline` пустые — так фронтенд отличает их для блока «Без срока»).
    Даты в ответе — в поясе `tz` (по умолчанию Europe/Moscow).
    Синхронный маршрут: FastAPI выполняет его в пуле потоков, сервер не блокируется.
    """
    zone = parse_timezone(tz)
    bootstrap_if_new(db, user, zone.key)

    today = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    date_from = date_from or today
    date_to = date_to or date_from + timedelta(days=DEFAULT_PERIOD_DAYS)
    if date_to <= date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Параметр `to` должен быть позже `from`.",
        )

    result = list_records_for_period(
        db, user.id, ListRecords(date_from=date_from, date_to=date_to, types=type)
    )
    records = result.records
    if include_undated:
        records = records + list_undated_records(db, user.id, type)
    return [_to_local(r, zone) for r in records]
