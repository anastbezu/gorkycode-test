"""Сервисы состояния разговора (backend-02a).

Состояние хранится в таблице `conversation_states`; наружу — только `schemas.ConversationState`.
Черновик действия (`pending`) дописывается на каждом шаге уточнения, не теряя уже сказанного.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from db import models
from schemas import ConversationState, LLMAction


class ConversationAccessError(PermissionError):
    """Разговор с таким id принадлежит другому пользователю."""


def get_conversation_state(
    db: Session, conversation_id: UUID, user_id: UUID
) -> ConversationState | None:
    """Состояние существующего разговора; разговора нет — `None`, без создания.

    Чужой разговор (тот же id, другой `user_id`) не отдаём: `ConversationAccessError`.
    """
    row = db.get(models.ConversationState, conversation_id)
    if row is None:
        return None
    if row.user_id != user_id:
        raise ConversationAccessError(
            f"разговор {conversation_id} принадлежит другому пользователю"
        )
    return ConversationState.model_validate(row)


def get_or_create_conversation_state(
    db: Session, conversation_id: UUID, user_id: UUID
) -> ConversationState:
    """Текущее состояние разговора; для нового разговора — пустое состояние, сохранённое в БД.

    Чужой разговор (тот же id, другой `user_id`) не отдаём: `ConversationAccessError`.
    """
    row = db.get(models.ConversationState, conversation_id)
    if row is None:
        row = models.ConversationState(conversation_id=conversation_id, user_id=user_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    elif row.user_id != user_id:
        raise ConversationAccessError(
            f"разговор {conversation_id} принадлежит другому пользователю"
        )
    return ConversationState.model_validate(row)


def save_conversation_state(db: Session, state: ConversationState) -> None:
    """Сохранить поля состояния из контракта.

    `focus_record_id`, `pending`, `candidates`, `missing`, `awaiting`.
    """
    row = db.get(models.ConversationState, state.conversation_id)
    if row is None:
        row = models.ConversationState(conversation_id=state.conversation_id, user_id=state.user_id)
        db.add(row)
    elif row.user_id != state.user_id:
        raise ConversationAccessError(
            f"разговор {state.conversation_id} принадлежит другому пользователю"
        )

    row.focus_record_id = state.focus_record_id
    row.pending = state.pending.model_dump(mode="json") if state.pending is not None else None
    row.candidates = list(state.candidates)
    row.missing = list(state.missing)
    row.awaiting = state.awaiting
    db.commit()


def merge_pending(state: ConversationState, incoming: dict[str, Any]) -> ConversationState:
    """Дописать в черновик `state.pending` непустые поля (`val is not None`) из `incoming`.

    Уже сохранённое не затирается: на втором шаге «в 14» добавляет `start`, а `title`
    из первого шага («встреча с Иваном») остаётся. Заполненные поля уходят из `missing`.
    Паттерн — livekit-booking-system, `context_manager._save`: берём старый черновик целиком
    и поверх кладём только непустые новые значения.
    """
    old = state.pending.root.model_dump() if state.pending is not None else {}
    merged = {**old, **{k: v for k, v in incoming.items() if v is not None}}
    pending = LLMAction.model_validate(merged)

    filled = pending.root.model_dump()
    missing = [name for name in state.missing if filled.get(name) is None]
    return state.model_copy(update={"pending": pending, "missing": missing})


def clear_pending(state: ConversationState) -> ConversationState:
    """Очистить черновик после успешного завершения действия: `pending`, `missing`, `awaiting`."""
    return state.model_copy(update={"pending": None, "missing": [], "awaiting": None})
