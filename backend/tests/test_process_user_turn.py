import asyncio
from uuid import uuid4

import httpx
import openai

from agent import agent as agent_module
from agent.agent import ActionParseError, process_user_turn
from schemas import CreateRecord


def turn(text="привет"):
    cid = uuid4()
    response = asyncio.run(process_user_turn(None, uuid4(), cid, text, "Europe/Moscow"))
    return cid, response


def test_llm_timeout_gives_polite_reply(monkeypatch):
    async def boom(*args, **kwargs):
        raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com"))

    monkeypatch.setattr(agent_module, "get_action", boom)
    cid, r = turn()
    assert "временно недоступен" in r.reply
    assert r.conversation_id == cid
    assert r.result is None


def test_unparseable_action_gives_polite_reply(monkeypatch):
    async def bad(*args, **kwargs):
        raise ActionParseError("мусор")

    monkeypatch.setattr(agent_module, "get_action", bad)
    _, r = turn()
    assert "Не удалось разобрать" in r.reply


def test_meeting_without_time_asks_question(monkeypatch):
    async def meeting(*args, **kwargs):
        return CreateRecord(type="meeting", title="встреча с Иваном", time_given=False)

    monkeypatch.setattr(agent_module, "get_action", meeting)
    _, r = turn("поставь встречу с Иваном завтра")
    assert r.awaiting == "answer"
    assert "время" in r.reply