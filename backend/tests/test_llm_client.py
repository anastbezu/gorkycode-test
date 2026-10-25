import pytest

from agent.llm import LLMConfigError, make_client
from schemas import LLMConfig


def test_model_from_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    _, model = make_client(None)
    assert model == "env-model"


def test_config_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    _, model = make_client(LLMConfig(model="cfg-model"))
    assert model == "cfg-model"


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MODEL", "env-model")
    with pytest.raises(LLMConfigError):
        make_client(None)


def test_empty_base_url_means_openai_default(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    client, _ = make_client(None)
    assert str(client.base_url).startswith("https://api.openai.com/")
