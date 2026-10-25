import os

from openai import AsyncOpenAI

from schemas import LLMConfig


class LLMConfigError(Exception):
    """Не хватает настроек LLM: ключа API или имени модели."""


def make_client(config: LLMConfig | None = None) -> tuple[AsyncOpenAI, str]:
    config = config or LLMConfig()

    # Пустая строка (LLM_BASE_URL= в .env) -> None: тогда SDK берёт адрес OpenAI по умолчанию.
    base_url = config.base_url or os.getenv("LLM_BASE_URL") or None
    api_key = config.api_key or os.getenv("LLM_API_KEY")
    model = config.model or os.getenv("LLM_MODEL")

    if not api_key:
        raise LLMConfigError("Не задан LLM_API_KEY")
    if not model:
        raise LLMConfigError("Не задан LLM_MODEL")

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=15, max_retries=1)
    return client, model
