import logging
from uuid import UUID

from schemas import ActionResult

log = logging.getLogger(__name__)


def focus_record_id(result: ActionResult) -> UUID | None:
    """Единственная созданная/показанная запись; пустая или множественная выдача снимает фокус."""
    if (
        result.ok
        and result.action in {"create_record", "list_records", "search_records"}
        and len(result.records) == 1
    ):
        return result.records[0].id
    return None

