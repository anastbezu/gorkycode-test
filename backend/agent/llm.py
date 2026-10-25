import os
from openai import AsyncOpenAI

from .models import LLMConfig


def make_client(config: LLMConfig | None = None) -> tuple[AsyncOpenAI, str]:
    config = config or LLMConfig()

    base_url = config.base_url or os.getenv("LLM_BASE_URL")
    api_key = config.api_key or os.getenv("LLM_API_KEY")
    model = config.model or os.getenv("LLM_MODEL")

    if not api_key:
        raise RuntimeError("Не задан LLM_API_KEY")
    if not model:
        raise RuntimeError("Не задан LLM_MODEL")

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=15, max_retries=1)
    return client, model
