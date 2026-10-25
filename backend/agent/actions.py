from datetime import datetime, timezone
from uuid import uuid4

from .models import (
    ActionResult,
    CreateRecord,
    ListRecords,
    Record,
    RecordType,
    SearchRecords,
)


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
        user_id=user_id or uuid4(),
        type=action.type,
        title=action.title,
        start=action.start,
        end=action.end,
        all_day=not action.time_given,
        deadline=action.deadline,
        created_at=datetime.now(timezone.utc),
    )
    return ActionResult(action="create_record", ok=True, records=[record])


async def handle_list_records(db, user_id, action: ListRecords) -> ActionResult:
    # TODO: replace with services.records.list_records_for_period(db, user_id, action)
    fake = Record(
        id=uuid4(),
        user_id=user_id or uuid4(),
        type=RecordType.MEETING,
        title="Встреча с командой",
        start=action.date_from,
        created_at=datetime.now(timezone.utc),
    )
    return ActionResult(action="list_records", ok=True, records=[fake])


async def handle_search_records(db, user_id, action: SearchRecords) -> ActionResult:
    # TODO: replace with search() from Rodion's module (agent-04)
    return ActionResult(action="search_records", ok=True, records=[])


ACTIONS = {
    "create_record": handle_create_record,
    "list_records": handle_list_records,
    "search_records": handle_search_records,
}


async def execute(db, user_id, action) -> ActionResult:
    handler = ACTIONS.get(action.action)
    if handler is None:
        return ActionResult(action=action.action, ok=False, error=f"неизвестное действие: {action.action}")
    return await handler(db, user_id, action)
