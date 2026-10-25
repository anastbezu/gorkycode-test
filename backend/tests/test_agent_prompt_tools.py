"""Smoke-проверки промпта, схем и локализации через pytest."""

import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.system_prompt import build_compact_system_prompt
from agent.tools import get_agent_tools, localize_tools


def test_prompt_calendar_and_timezone():
    # В UTC ещё воскресенье, в Токио уже понедельник следующей недели.
    now = datetime(2026, 10, 25, 20, 0, tzinfo=ZoneInfo("UTC"))
    prompt = build_compact_system_prompt(now, "Asia/Tokyo")

    assert len(prompt.splitlines()) <= 15
    assert "2026-10-26T05:00:00+09:00 (понедельник)" in prompt
    assert "2026-10-26T15:00:00+09:00" in prompt
    for day in range(14):
        expected = datetime(2026, 10, 26).date() + timedelta(days=day)
        assert expected.isoformat() in prompt
    assert "ask_user" in prompt

    with pytest.raises(ValueError):
        build_compact_system_prompt(datetime(2026, 10, 25), "Asia/Tokyo")


def test_localization_isolated_between_requests():
    base = [
        {
            "type": "function",
            "function": {
                "description": 'Формат {ISO_EXAMPLE}; JSON: {"x": 1}',
                "parameters": {
                    "$defs": {"Date": {"description": "Например {ISO_EXAMPLE}"}},
                    "properties": {
                        "start": {"anyOf": [{"description": "Дата {ISO_EXAMPLE}"}]},
                    },
                },
            },
        }
    ]
    original = deepcopy(base)
    moscow = datetime(2026, 10, 25, 10, tzinfo=ZoneInfo("Europe/Moscow"))
    tokyo = datetime(2026, 10, 25, 10, tzinfo=ZoneInfo("Asia/Tokyo"))
    first = localize_tools(base, moscow)
    second = localize_tools(base, tokyo)

    assert base == original
    assert "2026-10-25T15:00:00+03:00" in str(first)
    assert "2026-10-25T15:00:00+09:00" in str(second)
    assert "{ISO_EXAMPLE}" not in str(first)
    assert '{"x": 1}' in first[0]["function"]["description"]

    first[0]["function"]["parameters"]["properties"].clear()
    assert base == original
    assert "start" in second[0]["function"]["parameters"]["properties"]

    with pytest.raises(ValueError):
        localize_tools(base, datetime(2026, 10, 25))


def test_shared_create_record_json_and_tool_export():
    try:
        from schemas.actions import CreateRecord
    except ModuleNotFoundError as error:
        if error.name not in {"schemas", "schemas.actions"}:
            raise
        pytest.skip("Ожидается интеграция общих схем из develop")

    record = CreateRecord.model_validate_json(
        '{"action":"create_record","type":"meeting","title":"Тест",'
        '"start":"2026-10-25T15:00:00+03:00","time_given":true}'
    )
    assert record.start is not None
    assert record.start.utcoffset() == timedelta(hours=3)

    tools = get_agent_tools()
    assert {tool["function"]["name"] for tool in tools} == {
        "create_record",
        "list_records",
        "search_records",
        "ask_user",
    }
