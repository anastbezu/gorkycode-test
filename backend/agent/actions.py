import asyncio
from datetime import datetime

from schemas import (
    ActionResult,
    CreateRecord,
    Help,
    ListRecords,
    SearchRecords,
)
from services import create_record, list_records_for_period
from services.search_stub import search_by_substring  # TODO: заменить на search() из модуля Родиона


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
    # TODO: заменить на search(db, user_id, action.query, action.filters) из модуля Родиона
    hits = await asyncio.to_thread(
        search_by_substring, db, user_id, action.query, action.filters
    )
    return ActionResult(action="search_records", ok=True, records=[hit.record for hit in hits])


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
