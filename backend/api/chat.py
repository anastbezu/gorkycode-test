"""`POST /api/chat` — реплика пользователя → ответ ассистента (контракт docs/contracts/api.md)."""

import asyncio
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from agent.agent import process_user_turn
from db import get_session
from schemas import ChatRequest, ChatResponse
from services import (
    ConversationAccessError,
    get_conversation_state,
    get_or_create_conversation_state,
)

from .deps import CurrentUser, bootstrap_if_new, get_current_user_id, parse_timezone

router = APIRouter(prefix="/api", tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        400: {"description": "Заголовок X-User-Id не UUID"},
        404: {"description": "Разговор не найден: нет такого или он другого пользователя"},
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
      чужой или несуществующий `conversation_id` — 404;
    - `llm_config` принимается и не сохраняется (передаётся агенту в agent-05);
    - пользователь — заголовок `X-User-Id`; без него сервер выдаёт новый id в заголовке ответа
      и загружает стартовый датасет.

    Сервисы синхронные — вызываются через `asyncio.to_thread`, чтобы не блокировать сервер
    (`docs/decisions.md`, «Доступ к БД»).
    """
    zone = parse_timezone(req.timezone)

    # Проверки запроса — до импорта датасета: при ошибке клиент не получает X-User-Id,
    # и загруженные новому пользователю записи остались бы ничьими.
    if req.conversation_id is None:
        conversation_id = uuid4()
        await asyncio.to_thread(get_or_create_conversation_state, db, conversation_id, user.id)
    else:
        conversation_id = req.conversation_id
        try:
            state = await asyncio.to_thread(get_conversation_state, db, conversation_id, user.id)
        except ConversationAccessError:
            state = None
        if state is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Разговор не найден. Начните новый разговор (conversation_id = null).",
            )

    await asyncio.to_thread(bootstrap_if_new, db, user, zone.key)

    return await process_user_turn(
        db, user.id, conversation_id, req.text, zone.key, req.llm_config
    )
