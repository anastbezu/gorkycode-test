"""Экспорт общих Pydantic-схем и локализация описаний на один запрос."""

from copy import deepcopy
from datetime import datetime
from importlib import import_module

from .system_prompt import format_iso_example


def get_agent_tools() -> list[dict]:
    """Экспортировать четыре действия без подстановки {ISO_EXAMPLE}.

    Импорт отложен до вызова: до интеграции схем Дениса остальные функции
    агента доступны. Временных копий моделей здесь нет.
    """
    # Поддерживаются импорты agent.tools из backend и backend.agent.tools
    # из корня проекта. В обоих случаях используется один каталог schemas.
    parent_package = __package__.rpartition(".")[0]
    module_name = (
        f"{parent_package}.schemas.actions" if parent_package else "schemas.actions"
    )
    try:
        actions = import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name not in {module_name, module_name.rpartition(".")[0]}:
            raise
        raise RuntimeError(
            "Общие backend/schemas ещё не подключены. Дождитесь их интеграции "
            "из develop; создавать копии моделей в агенте не нужно."
        ) from error

    tools = []
    for model in (
        actions.CreateRecord,
        actions.ListRecords,
        actions.SearchRecords,
        actions.AskUser,
    ):
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
