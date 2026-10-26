"""Экспорт общих Pydantic-схем и локализация описаний на один запрос."""

from copy import deepcopy
from datetime import datetime

from schemas import AskUser, CreateRecord, Help, ListRecords, SearchRecords

from .system_prompt import format_iso_example


def get_agent_tools() -> list[dict]:
    """Экспортировать доступные действия без подстановки {ISO_EXAMPLE}."""
    tools = []
    for model in (CreateRecord, ListRecords, SearchRecords, AskUser, Help):
        parameters = model.model_json_schema()
        description = parameters.pop("description", model.__name__)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": model.model_fields["action"].default,
                    "description": description,
                    "parameters": parameters,
                },
            }
        )
    return tools


def localize_tools(tools: list[dict], now: datetime) -> list[dict]:
    """Вернуть глубокую копию с ISO-примером в описаниях всех вложенных полей.

    now — aware datetime в поясе пользователя, общий с промптом на этот запрос.
    Другие фигурные скобки и исходные схемы остаются без изменений.
    """
    example = format_iso_example(now)
    localized = deepcopy(tools)

    def replace_descriptions(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "description" and isinstance(item, str):
                    value[key] = item.replace("{ISO_EXAMPLE}", example)
                else:
                    replace_descriptions(item)
        elif isinstance(value, list):
            for item in value:
                replace_descriptions(item)

    replace_descriptions(localized)
    return localized
