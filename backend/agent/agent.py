import json
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import openai
from pydantic import ValidationError

from schemas import AskUser, ChatResponse, LLMAction, LLMConfig

from .actions import execute
from .llm import make_client
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
):
    """Один вызов LLM: модель обязана выбрать один из четырёх инструментов."""
    client, model = make_client(llm_config)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": build_compact_system_prompt(now, timezone_name)},
            {"role": "user", "content": text},
        ],
        tools=localize_tools(get_agent_tools(), now),
        tool_choice="required",
    )
    message = response.choices[0].message

    if not message.tool_calls:
        raise ActionParseError("модель не вернула действие")

    call = message.tool_calls[0]
    try:
        args = json.loads(call.function.arguments)
        return LLMAction.model_validate({"action": call.function.name, **args}).root
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        raise ActionParseError(str(e)) from e


async def process_user_turn(
    db,
    user_id: UUID,
    conversation_id: UUID,
    text: str,
    timezone_name: str,
    llm_config: LLMConfig | None = None,
) -> ChatResponse:
    # Один снимок времени на запрос: общий для промпта и описаний инструментов.
    now = datetime.now(ZoneInfo(timezone_name))
    try:
        action = await get_action(text, now, timezone_name, llm_config)
    except openai.APIError:
        # таймаут, сеть, лимиты, 5xx
        return ChatResponse(
            conversation_id=conversation_id,
            reply="Сервис распознавания временно недоступен. Попробуйте ещё раз чуть позже.",
        )
    except ActionParseError:
        return ChatResponse(
            conversation_id=conversation_id,
            reply="Не удалось разобрать запрос. Попробуйте сформулировать иначе.",
        )

    if isinstance(action, AskUser):
        return ChatResponse(
            conversation_id=conversation_id, reply=action.question, awaiting="answer"
        )

    result = await execute(db, user_id, action)

    if not result.ok and result.missing:
        return ChatResponse(
            conversation_id=conversation_id,
            reply=question_for_missing(result.missing),
            result=result,
            awaiting="answer",
        )

    return ChatResponse(
        conversation_id=conversation_id,
        reply=reply_for_result(result, timezone_name),
        result=result,
    )
