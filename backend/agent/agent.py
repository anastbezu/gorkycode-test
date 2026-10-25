import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .llm import make_client
from .models import LLMAction, LLMConfig
from ._tmp_tools import TOOLS

def build_system_prompt() -> str:
    # TODO: заменить на промпт из agent-01 (Давид)
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    return (
        "Ты ассистент для задач и встреч. "
        f"Сейчас {now.isoformat()} (Europe/Moscow). "
        "Даты возвращай в ISO 8601 со смещением часового пояса."
    )


async def get_action(text: str, llm_config: LLMConfig | None = None):
    client, model = make_client(llm_config)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": text},
        ],
        tools=TOOLS,
        tool_choice="required",
    )
    message = response.choices[0].message

    if not message.tool_calls:
        raise RuntimeError("Модель не вернула действие")

    call = message.tool_calls[0]
    args = json.loads(call.function.arguments)
    return LLMAction.model_validate({"action": call.function.name, **args}).root
