import json
from asyncio import to_thread
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import openai
from pydantic import ValidationError

from schemas import AskUser, ChatResponse, CreateRecord, LLMAction, LLMConfig
from services.conversation import (
    clear_pending,
    get_or_create_conversation_state,
    merge_pending,
    save_conversation_state,
)
from services.records import get_record

from .actions import execute
from .context import build_draft_context, build_focus_context
from .focus import focus_record_id
from .llm import LLMConfigError, make_client
from .replies import question_for_missing, reply_for_result
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
    context = [build_draft_context(state)]
    if state.focus_record_id is not None:
        record = await to_thread(get_record, db, user_id, state.focus_record_id)
        if record is not None:
            context.append(build_focus_context(record, timezone_name))
        else:
            state.focus_record_id = None
    try:
        action = await get_action(
            text, now, timezone_name, llm_config, context="\n".join(filter(None, context))
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
        # Вопрос не заменяет действие: иначе теряются type/title первого шага.
        if state.pending is None:
            state.missing = action.missing
        state.awaiting = "answer"
        state.candidates = []
        await to_thread(save_conversation_state, db, state)
        return ChatResponse(
            conversation_id=conversation_id, reply=action.question, awaiting="answer"
        )

    continuing = (
        state.awaiting == "answer"
        and state.pending is not None
        and isinstance(state.pending.root, CreateRecord)
        and isinstance(action, CreateRecord)
        and state.pending.root.type == action.type
    )
    if (
        isinstance(action, CreateRecord)
        and state.pending is not None
        and isinstance(state.pending.root, CreateRecord)
        and state.pending.root.type != action.type
    ):
        state = clear_pending(state)
        state.candidates = []
    if continuing:
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

    result = await execute(db, user_id, action, now=now)

    if not result.ok and result.missing:
        state.pending = LLMAction(action)
        question = AskUser(
            question=question_for_missing(result.missing), missing=result.missing
        )
        state.missing = question.missing
        state.awaiting = "answer"
        state.candidates = []
        await to_thread(save_conversation_state, db, state)
        return ChatResponse(
            conversation_id=conversation_id,
            reply=question.question,
            result=result,
            awaiting="answer",
        )

    if result.ok:
        # Список/поиск во время уточнения не уничтожает незавершённое создание.
        if continuing or state.pending is None:
            state = clear_pending(state)
            state.candidates = []
        if result.action in {"create_record", "list_records", "search_records"}:
            state.focus_record_id = focus_record_id(result)
    await to_thread(save_conversation_state, db, state)

    return ChatResponse(
        conversation_id=conversation_id,
        reply=reply_for_result(result, timezone_name, action=action, now=now),
        result=result,
        awaiting=state.awaiting,
    )
