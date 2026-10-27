import json
from asyncio import to_thread
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import openai
from pydantic import ValidationError

from schemas import AskUser, ChatResponse, CreateRecord, LLMAction, LLMConfig
from services.conversation import (
    get_or_create_conversation_state,
    merge_pending,
    save_conversation_state,
)
from services.records import get_record

from .actions import execute
from .change_replies import reply_for_change
from .changes import CHANGE_ACTIONS, execute_change
from .context import build_state_context, record_summary
from .llm import LLMConfigError, make_client
from .presentation import MAX_SHOWN
from .replies import question_for_missing, reply_for_result
from .state import (
    complete_from_draft,
    continues_pending,
    is_refusal,
    pending_draft,
    reset_pending,
    update_state,
)
from .system_prompt import build_compact_system_prompt
from .tools import get_agent_tools, localize_tools


class ActionParseError(Exception):
    """Модель вернула действие, которое не удалось разобрать."""


async def get_action(
    text: str,
    now: datetime,
    timezone_name: str,
    llm_config: LLMConfig | None = None,
    *,
    context: str = "",
):
    """Один вызов LLM: модель выбирает один из опубликованных инструментов."""
    client, model = make_client(llm_config)
    prompt = build_compact_system_prompt(now, timezone_name)
    if context:
        prompt += "\n" + context
    tools = localize_tools(get_agent_tools(), now)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        tools=tools,
        tool_choice="required",
    )
    if not response.choices:
        raise ActionParseError("модель вернула пустой ответ")
    message = response.choices[0].message

    if not message.tool_calls or len(message.tool_calls) != 1:
        raise ActionParseError("модель должна вернуть ровно одно действие")

    call = message.tool_calls[0]
    if call.function.name not in {tool["function"]["name"] for tool in tools}:
        raise ActionParseError("модель выбрала недоступный инструмент")
    try:
        args = json.loads(call.function.arguments)
        return LLMAction.model_validate({**args, "action": call.function.name}).root
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        raise ActionParseError(str(e)) from e


async def process_user_turn(
    db,
    user_id: UUID,
    conversation_id: UUID,
    text: str,
    timezone_name: str,
    llm_config: LLMConfig | None = None,
    *,
    now: datetime | None = None,
) -> ChatResponse:
    # Один снимок времени на запрос: общий для промпта, описаний инструментов и сервисов.
    # Готовый now подставляют автотесты (agent-08).
    zone = ZoneInfo(timezone_name)
    now = now.astimezone(zone) if now is not None else datetime.now(zone)
    state = await to_thread(get_or_create_conversation_state, db, conversation_id, user_id)
    if is_refusal(text, state):
        creating = state.pending is not None and isinstance(state.pending.root, CreateRecord)
        state = reset_pending(state)
        await to_thread(save_conversation_state, db, state)
        return ChatResponse(
            conversation_id=conversation_id,
            reply="Хорошо, не ставлю." if creating else "Хорошо, ничего не меняю.",
        )

    # Один Session: чтения последовательные, все записи проверяются по user_id.
    ids = list(state.shown[:MAX_SHOWN])
    if state.focus_record_id is not None:
        ids.append(state.focus_record_id)
    if state.last_action is not None:
        ids.extend(state.last_action.record_ids[:3])
    records = {}
    for rid in dict.fromkeys(ids):
        record = await to_thread(get_record, db, user_id, rid)
        if record is not None and record.user_id == user_id and record.id == rid:
            records[rid] = record
    if state.focus_record_id not in records:
        state.focus_record_id = None
    context = build_state_context(state, records, timezone_name)
    try:
        action = await get_action(
            text, now, timezone_name, llm_config, context=context
        )
    except LLMConfigError:
        return ChatResponse(
            conversation_id=conversation_id,
            reply="Ассистент не настроен: не указан ключ API или модель LLM. "
            "Задайте их в настройках.",
            awaiting=state.awaiting,
        )
    except openai.APIError:
        # таймаут, сеть, лимиты, 5xx
        return ChatResponse(
            conversation_id=conversation_id,
            reply="Сервис распознавания временно недоступен. Попробуйте ещё раз чуть позже.",
            awaiting=state.awaiting,
        )
    except ActionParseError:
        return ChatResponse(
            conversation_id=conversation_id,
            reply="Не удалось разобрать запрос. Попробуйте сформулировать иначе.",
            awaiting=state.awaiting,
        )

    if isinstance(action, AskUser):
        state = update_state(state, action, None)
        await to_thread(save_conversation_state, db, state)
        return ChatResponse(
            conversation_id=conversation_id, reply=action.question, awaiting=state.awaiting
        )

    continuing = (
        continues_pending(state, action)
        and isinstance(action, CreateRecord)
    )
    ask = pending_draft(state)
    if continuing and ask is not None:
        # Ответ на вопрос с частичным черновиком (AskUser.draft): дополнить уже названное.
        action = complete_from_draft(ask, action, timezone_name)
    elif continuing:
        # LLM возвращает полное действие, но дописываем только ожидаемые слоты.
        # type/title и неназванные end/deadline из черновика остаются неизменными.
        fields = set(state.missing) & {"start", "end", "deadline"}
        if "start" in fields:
            fields.add("time_given")
        incoming = action.model_dump(include=fields, exclude_none=True)
        if "start" not in incoming:
            # Один флаг без нового времени не превращает дату черновика в полночь встречи.
            incoming.pop("time_given", None)
        merged = merge_pending(state, incoming)
        state.pending = merged.pending
        # missing из merge_pending проверяет лишь None, а не бизнес-правила.
        # Сохраняем ожидание до ответа сервиса (включая ошибки и дату без времени).
        action = state.pending.root

    change = None
    if action.action in CHANGE_ACTIONS:
        # Изменение, статус, откат: нужна цель из состояния и прежние значения для отката.
        change = await execute_change(db, user_id, action, state, now=now)
        result = change.result
    else:
        result = await execute(db, user_id, action, now=now)

    state = update_state(state, action, result, before=change.before if change else None)
    await to_thread(save_conversation_state, db, state)

    if change is not None:
        reply = reply_for_change(change, action, timezone_name)
    elif result.candidates:
        choices = "; ".join(
            f"{index}) {record_summary(record, timezone_name)}"
            for index, record in enumerate(result.candidates[:MAX_SHOWN], 1)
        )
        reply = f"Какую запись выбрать? {choices}."
    elif not result.ok and result.missing:
        reply = question_for_missing(result.missing)
    else:
        reply = reply_for_result(result, timezone_name, action=action, now=now)
    if state.pending_skipped and state.pending is not None:
        pending = state.pending.root
        title = getattr(pending, "title", None)
        reminder = f"Запись «{title}» ещё не создана." if title else "Действие ещё не завершено."
        reply += " " + reminder + " " + question_for_missing(state.missing)

    return ChatResponse(
        conversation_id=conversation_id,
        reply=reply,
        result=result,
        awaiting=state.awaiting,
    )
