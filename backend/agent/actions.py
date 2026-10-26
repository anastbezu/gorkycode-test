import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from schemas import (
    ActionResult,
    CreateRecord,
    ListRecords,
    Record,
    RecordType,
    SearchRecords,
)
from services import list_records_for_period
from services.search_stub import search_by_substring  # TODO: заменить на search() из модуля Родиона


async def handle_create_record(db, user_id, action: CreateRecord) -> ActionResult:
    # TODO: replace with services.records.create_record(db, user_id, action)
    if action.type is RecordType.MEETING and (not action.time_given or action.start is None):
        return ActionResult(
            action="create_record",
            ok=False,
            missing=["start"],
            error="не названо время встречи",
        )
    record = Record(
        id=uuid4(),
        user_id=user_id,
        type=action.type,
        title=action.title,
        start=action.start,
        end=action.end,
        all_day=not action.time_given,
        deadline=action.deadline,
        created_at=datetime.now(UTC),
    )
    return ActionResult(action="create_record", ok=True, records=[record])


async def handle_list_records(db, user_id, action: ListRecords) -> ActionResult:
    return await asyncio.to_thread(list_records_for_period, db, user_id, action)


async def handle_search_records(db, user_id, action: SearchRecords) -> ActionResult:
    # TODO: заменить на search(user_id, action.query, action.filters) из модуля Родиона
    hits = await asyncio.to_thread(
        search_by_substring, db, user_id, action.query, action.filters
    )
    return ActionResult(action="search_records", ok=True, records=[hit.record for hit in hits])


ACTIONS = {
    "create_record": handle_create_record,
    "list_records": handle_list_records,
    "search_records": handle_search_records,
}


async def execute(db, user_id, action) -> ActionResult:
    handler = ACTIONS.get(action.action)
    if handler is None:
        return ActionResult(
            action=action.action, ok=False, error=f"неизвестное действие: {action.action}"
        )
    return await handler(db, user_id, action)
