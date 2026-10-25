import pytest

from agent.llm import make_client
from agent.models import LLMConfig


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
    with pytest.raises(RuntimeError):
        make_client(None)
