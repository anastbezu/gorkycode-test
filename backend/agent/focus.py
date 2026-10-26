import asyncio
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from schemas import ActionResult
from services import (
    ConversationAccessError,
    get_or_create_conversation_state,
    save_conversation_state,
)


def _save_focus(db, conversation_id: UUID, user_id: UUID, record_id: UUID) -> None:
    try:
        state = get_or_create_conversation_state(db, conversation_id, user_id)
        save_conversation_state(db, state.model_copy(update={"focus_record_id": record_id}))
    except SQLAlchemyError:
        db.rollback()


async def remember_focus(db, user_id: UUID, conversation_id: UUID, result: ActionResult) -> None:
    """Если поиск нашёл одну запись, сделать её фокусом разговора («перенеси её»)."""
    record_id = focus_record_id(result)
    if record_id is None:
        return
    try:
        await asyncio.to_thread(_save_focus, db, conversation_id, user_id, record_id)
    except ConversationAccessError:
        return


def focus_record_id(result: ActionResult) -> UUID | None:
    """Запись, которая становится «ей» в диалоге: единственное совпадение поиска."""
    if result.ok and result.action == "search_records" and len(result.records) == 1:
        return result.records[0].id
    return None