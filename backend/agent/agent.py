import json
import openai
from uuid import UUID
from datetime import datetime
from zoneinfo import ZoneInfo
from pydantic import ValidationError

from .llm import make_client
from .models import LLMAction, LLMConfig, AskUser, ChatResponse
from ._tmp_tools import TOOLS
from .actions import execute
from .replies import question_for_missing, reply_for_result


class ActionParseError(Exception):
    """Модель вернула действие, которое не удалось разобрать."""


def build_system_prompt(timezone_name: str) -> str:
    # TODO: заменить на build_compact_system_prompt из agent-01 (Давид)
    now = datetime.now(ZoneInfo(timezone_name))
    return (
        "Ты ассистент для задач и встреч. "
        f"Сейчас {now.isoformat()} ({timezone_name}). "
        "Даты возвращай в ISO 8601 со смещением часового пояса."
    )


async def get_action(text: str, timezone_name: str, llm_config: LLMConfig | None = None):
    client, model = make_client(llm_config)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": build_system_prompt(timezone_name)},
            {"role": "user", "content": text},
        ],
        tools=TOOLS,
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
    try:
        action = await get_action(text, timezone_name, llm_config)
    except openai.APIError:
        # таймаут, сеть, лимиты, 5xx
        return ChatResponse(
            conversation_id=conversation_id,
            reply="Сервис распознавания временно недоступен. Попробуйте ещё раз чуть позже.",
        )
    except ActionParseError:
        return ChatResponse(conversation_id=conversation_id, reply="Не удалось разобрать запрос. Попробуйте сформулировать иначе.")   # «Не удалось разобрать запрос...»

    if isinstance(action, AskUser):
        return ChatResponse(conversation_id=conversation_id, reply=action.question, awaiting="answer")

    result = await execute(db, user_id, action)

    if not result.ok and result.missing:
        return ChatResponse(conversation_id=conversation_id, reply=question_for_missing(result.missing), result=result, awaiting="answer")

    return ChatResponse(conversation_id=conversation_id, reply=reply_for_result(result, timezone_name), result=result)