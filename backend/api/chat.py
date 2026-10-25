"""`POST /api/chat` — реплика пользователя → ответ ассистента (контракт docs/contracts/api.md)."""

import asyncio
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from db import get_session
from schemas import ChatRequest, ChatResponse
from services import ConversationAccessError, get_or_create_conversation_state

from .deps import CurrentUser, bootstrap_if_new, get_current_user_id, parse_timezone
from .dispatch import handle_without_llm

router = APIRouter(prefix="/api", tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        404: {"description": "Разговор не найден (принадлежит другому пользователю)"},
        422: {"description": "Неверное тело запроса или неизвестный часовой пояс"},
    },
)
async def chat(
    req: ChatRequest,
    user: CurrentUser = Depends(get_current_user_id),
    db: Session = Depends(get_session),
) -> ChatResponse:
    """Реплика пользователя → ответ ассистента.

    - `conversation_id = null` — новый разговор, сервер присваивает ему id;
    - `llm_config` принимается и не сохраняется (передаётся агенту в agent-05);
    - пользователь — заголовок `X-User-Id`; без него сервер выдаёт новый id в заголовке ответа
      и загружает стартовый датасет.

    Сервисы синхронные — вызываются через `asyncio.to_thread`, чтобы не блокировать сервер
    (`docs/decisions.md`, «Доступ к БД»).
    """
    parse_timezone(req.timezone)
    await asyncio.to_thread(bootstrap_if_new, db, user, req.timezone)

    conversation_id = req.conversation_id or uuid4()
    try:
        await asyncio.to_thread(get_or_create_conversation_state, db, conversation_id, user.id)
    except ConversationAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Разговор не найден. Начните новый разговор (conversation_id = null).",
        ) from exc

    # TODO(agent-05): заменить на
    #   await process_user_turn(db, user.id, conversation_id, req.text, req.timezone,
    #                           req.llm_config)
    return await asyncio.to_thread(handle_without_llm, db, user.id, conversation_id, req)
