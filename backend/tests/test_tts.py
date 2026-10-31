"""TTS: маршрут с настоящей авторизацией (БД подменена), Gemini без сети."""

import asyncio
import base64
import io
import json
import wave
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

import api.deps as deps
import api.tts as route
import tts.client as gemini
from db import get_session
from main import app
from stt.rate_limit import RateLimiter

pytestmark = pytest.mark.anyio
REAL_CLIENT = httpx.AsyncClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def wav():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b"\x01\x02" * 2400)
    return buffer.getvalue()


def payload(audio):
    return {
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "audio",
                        "mime_type": "audio/wav",
                        "data": base64.b64encode(audio).decode(),
                    }
                ],
            }
        ]
    }


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    for name, value in {
        "TTS_ENABLED": "1",
        "TTS_API_KEY": "secret-test-key",
        "TTS_MODEL": "tts-test-model",
        "TTS_VOICE": "Kore",
    }.items():
        monkeypatch.setenv(name, value)
    route.rate_limiter.reset()
    route.global_rate_limiter.reset()
    monkeypatch.setattr(deps, "touch_guest", lambda *_: SimpleNamespace(login=None))
    monkeypatch.setattr(
        deps,
        "user_by_token",
        lambda _, token: SimpleNamespace(id=uuid4()) if token == "valid" else None,
    )
    app.dependency_overrides[get_session] = lambda: object()
    yield
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
async def client():
    async with REAL_CLIENT(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def mock_provider(monkeypatch, handler):
    monkeypatch.setattr(
        gemini.httpx,
        "AsyncClient",
        lambda **kwargs: REAL_CLIENT(transport=httpx.MockTransport(handler), **kwargs),
    )


async def test_success_exact_text_config_and_guest_header(client, monkeypatch, wav):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload(wav))

    mock_provider(monkeypatch, handler)
    text = " Встреча с Иваном 05.03.2026 в 15:45. "
    response = await client.post("/api/tts", json={"text": text})
    assert response.status_code == 200
    assert response.content == wav
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["X-User-Id"]
    body = json.loads(requests[0].content)
    assert body["input"][0]["content"][0]["text"] == text
    assert body["model"] == "tts-test-model"
    assert body["generation_config"]["speech_config"] == [{"voice": "Kore"}]
    assert requests[0].headers["x-goog-api-key"] == "secret-test-key"
    assert "secret-test-key" not in str(requests[0].url)


async def test_account_auth(client, monkeypatch, wav):
    mock_provider(monkeypatch, lambda _: httpx.Response(200, json=payload(wav)))
    response = await client.post(
        "/api/tts",
        json={"text": "Ответ"},
        headers={"Authorization": "Bearer valid", "X-User-Id": "bad"},
    )
    assert response.status_code == 200
    assert "X-User-Id" not in response.headers


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"X-User-Id": "bad"}, 400),
        ({"Authorization": "Bearer expired"}, 401),
        ({"Authorization": "Basic bad"}, 401),
    ],
)
async def test_auth_errors(client, headers, status):
    response = await client.post("/api/tts", json={"text": "Ответ"}, headers=headers)
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": ""},
        {"text": " \n "},
        {"text": None},
        {"text": 123},
        {"text": "я" * 1001},
        {"text": "Ответ", "llm_config": {}},
        ["Ответ"],
    ],
)
async def test_validation(client, body):
    response = await client.post("/api/tts", json=body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


async def test_invalid_json(client):
    response = await client.post(
        "/api/tts", content=b"{", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize(
    ("setting", "value"),
    [("TTS_ENABLED", "0"), ("TTS_API_KEY", ""), ("TTS_MODEL", ""), ("TTS_VOICE", "")],
)
async def test_disabled_no_network(client, monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    mock_provider(monkeypatch, lambda _: pytest.fail("network must not be called"))
    response = await client.post("/api/tts", json={"text": "Ответ"})
    assert response.status_code == 503


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
async def test_provider_errors_no_retry_no_leak(client, monkeypatch, caplog, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="secret-test-key PRIVATE REPLY")

    mock_provider(monkeypatch, handler)
    response = await client.post("/api/tts", json={"text": "PRIVATE REPLY"})
    assert response.status_code == 503
    assert len(calls) == 1
    assert "secret-test-key" not in caplog.text + response.text
    assert "PRIVATE REPLY" not in caplog.text + response.text


@pytest.mark.parametrize("kind", ["timeout", "network", "deadline"])
async def test_connection_failures(client, monkeypatch, kind):
    async def handler(request):
        if kind == "deadline":
            await asyncio.sleep(1)
        if kind == "network":
            raise httpx.ConnectError("unreachable")
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(gemini, "TIMEOUT_SECONDS", 0.01)
    mock_provider(monkeypatch, handler)
    response = await client.post("/api/tts", json={"text": "Ответ"})
    assert response.status_code == 503


@pytest.mark.parametrize("kind", ["json", "empty", "base64", "mime", "truncated", "shape", "size"])
async def test_bad_audio(client, monkeypatch, wav, kind):
    body = payload(wav)
    if kind == "empty":
        body = {"steps": []}
    elif kind == "base64":
        body["steps"][0]["content"][0]["data"] = "%%%"
    elif kind == "mime":
        body["steps"][0]["content"][0]["mime_type"] = "audio/mpeg"
    elif kind == "truncated":
        body = payload(wav[:-4])
    elif kind == "shape":
        body = {"steps": [None]}
    elif kind == "size":
        monkeypatch.setattr(gemini, "MAX_RESPONSE_BYTES", 1)
    mock_provider(
        monkeypatch,
        lambda _: (
            httpx.Response(200, content=b"invalid")
            if kind == "json"
            else httpx.Response(200, json=body)
        ),
    )
    response = await client.post("/api/tts", json={"text": "Ответ"})
    assert response.status_code == 503


@pytest.mark.parametrize("global_limit", [False, True])
async def test_limits(client, monkeypatch, wav, global_limit):
    mock_provider(monkeypatch, lambda _: httpx.Response(200, json=payload(wav)))
    limiter = "global_rate_limiter" if global_limit else "rate_limiter"
    monkeypatch.setattr(route, limiter, RateLimiter(1, 60))
    headers = {"X-User-Id": str(uuid4())}
    assert (
        await client.post("/api/tts", json={"text": "Ответ"}, headers=headers)
    ).status_code == 200
    if global_limit:
        headers = {"X-User-Id": str(uuid4())}
    response = await client.post("/api/tts", json={"text": "Ответ"}, headers=headers)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
