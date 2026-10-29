import asyncio
from datetime import datetime

from schemas import (
    ActionResult,
    CreateRecord,
    Help,
    ListRecords,
    SearchRecords,
)
from search import search
from services import create_record, list_records_for_period


class SearchResult(ActionResult):
    """Результат поиска для ответа: `similar` — точных нет, это похожие (search.md).

    Признак только для шаблона ответа: в `ChatResponse.result` поле объявлено как
    `ActionResult`, поэтому наружу `similar` не уходит и контракт API не меняется.
    """

    similar: bool = False


async def handle_create_record(
    db, user_id, action: CreateRecord, now: datetime | None = None
) -> ActionResult:
    return await asyncio.to_thread(create_record, db, user_id, action, now=now)


async def handle_list_records(
    db, user_id, action: ListRecords, now: datetime | None = None
) -> ActionResult:
    return await asyncio.to_thread(list_records_for_period, db, user_id, action)


async def handle_search_records(
    db, user_id, action: SearchRecords, now: datetime | None = None
) -> ActionResult:
    hits = await asyncio.to_thread(search, db, user_id, action.query, action.filters)
    similar = bool(hits) and all(hit.match == "similar" for hit in hits)
    return SearchResult(
        action="search_records", ok=True, records=[hit.record for hit in hits], similar=similar
    )


async def handle_help(db, user_id, action: Help, now: datetime | None = None) -> ActionResult:
    return ActionResult(action="help", ok=True)


ACTIONS = {
    "create_record": handle_create_record,
    "list_records": handle_list_records,
    "search_records": handle_search_records,
    "help": handle_help,
}


async def execute(db, user_id, action, *, now: datetime | None = None) -> ActionResult:
    handler = ACTIONS.get(action.action)
    if handler is None:
        return ActionResult(
            action=action.action, ok=False, error=f"неизвестное действие: {action.action}"
        )
    return await handler(db, user_id, action, now=now)
