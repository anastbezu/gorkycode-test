"""`POST /api/chat` — реплика пользователя → ответ ассистента (контракт docs/contracts/api.md)."""

import asyncio
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from agent.agent import process_user_turn
from db import get_session
from gcal.sync import NOT_SENT_TEXT, changed_record_ids, mark_pending, sync_after_turn
from schemas import ChatRequest, ChatResponse
from services import (
    ConversationAccessError,
    get_conversation_state,
    get_or_create_conversation_state,
)

from .deps import CurrentUser, get_current_user_id, parse_timezone

router = APIRouter(prefix="/api", tags=["chat"])
log = logging.getLogger("uvicorn.error")


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        400: {"description": "Заголовок X-User-Id не UUID"},
        401: {"description": "Токен учётки недействителен"},
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
    - пользователь — учётка по токену или гость по `X-User-Id` (`api/deps.py`); новый гость
      начинает с пустым календарём.

    Сервисы синхронные — вызываются через `asyncio.to_thread`, чтобы не блокировать сервер
    (`docs/decisions.md`, «Доступ к БД»).

    Один коммит на реплику: сервисы и агент только пишут в сессию, коммитит маршрут — после
    того как реплика обработана. Любое исключение — откат всего, что сделала реплика
    (записи и состояние разговора), и 500. Строку нового гостя зависимость пользователя
    коммитит сама, до реплики.
    """
    zone = parse_timezone(req.timezone)

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

    try:
        response = await process_user_turn(
            db, user.id, conversation_id, req.text, zone.key, req.llm_config
        )
        changed = changed_record_ids(response.result)
        if user.is_account and changed:
            # «Ждут отправки в Google» — в той же транзакции, что и само изменение.
            await asyncio.to_thread(mark_pending, db, user.id, changed)
        await asyncio.to_thread(db.commit)
    except BaseException:
        await asyncio.to_thread(db.rollback)
        raise
    if user.is_account:
        await _sync_google(db, user.id, zone.key, response, bool(changed))
    return response


async def _sync_google(db: Session, user_id, tz: str, response: ChatResponse,
                       changed: bool) -> None:
    """Google Календарь — после коммита: реплика уже сохранена, Google её не откатит.
    Любой сбой здесь не ломает ответ: запись ждёт и уйдёт при следующем запросе."""
    try:
        result = await asyncio.to_thread(sync_after_turn, db, user_id, tz)
    except Exception:  # noqa: BLE001 — сбой синхронизации не должен ронять ответ ассистента
        await asyncio.to_thread(db.rollback)
        log.exception("Синхронизация с Google Календарём упала")
        result = None
    if result is not None and not result.ok and changed:
        response.reply = f"{response.reply} {NOT_SENT_TEXT}"
