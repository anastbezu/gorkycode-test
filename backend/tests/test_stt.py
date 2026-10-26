"""`POST /api/stt` (voice-01) — без сети: провайдер распознавания подменён.

Записи в `fixtures/audio/` — настоящие файлы: `chrome_2s.webm` и `chrome_2s_opus.mp4` записаны
MediaRecorder в Chromium, `aac_2s_fragmented.mp4` (AAC во фрагментированном MP4, как у Safari)
и `opus_2s.ogg` — ffmpeg. MP4 хранятся в base64 (`.mp4.b64`): некоторые инструменты при
копировании дописывают в MP4 свои метаданные, а текст доходит байт в байт.
Длинные записи собираются в тестах: так репозиторий не растёт.
"""

import base64
import json
import struct
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

import api.stt as stt_route
import stt.client as stt_client
from main import app
from stt import STTUnavailableError, duration_seconds

pytestmark = pytest.mark.anyio

AUDIO = Path(__file__).parent / "fixtures" / "audio"
PHRASE = "Поставь встречу с Иваном завтра в 15:00"


def _fixture(name: str) -> bytes:
    encoded = AUDIO / f"{name}.b64"
    if encoded.exists():
        return base64.b64decode(encoded.read_text())
    return (AUDIO / name).read_bytes()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_rate_limit() -> None:
    stt_route.rate_limiter.reset()


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[bytes, str]]:
    """Провайдер подменён: возвращает фразу и запоминает, что ему отправили."""
    sent: list[tuple[bytes, str]] = []

    async def fake_transcribe(audio: bytes, content_type: str) -> str:
        sent.append((audio, content_type))
        return PHRASE

    monkeypatch.setattr(stt_route, "transcribe", fake_transcribe)
    return sent


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _wav(seconds: float, rate: int = 8000) -> bytes:
    """Несжатый WAV: 8 кГц, моно, 8 бит — 31 секунда весит ~250 КБ."""
    data = b"\x80" * int(seconds * rate)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate, 1, 8)
    return (
        b"RIFF"
        + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


def _webm(last_block_ms: int) -> bytes:
    """WebM как у Chrome: размер Segment и Cluster неизвестен, длительности в заголовке нет."""
    unknown = b"\x01\xff\xff\xff\xff\xff\xff\xff"
    ebml_header = b"\x1a\x45\xdf\xa3\x84" + b"\x42\x82\x81\x77"  # DocType-заглушка
    cluster_time = b"\xe7\x84" + struct.pack(">I", last_block_ms)
    block = b"\xa3\x88" + b"\x81" + struct.pack(">h", 0) + b"\x80" + b"opus"
    return (
        ebml_header
        + b"\x18\x53\x80\x67"
        + unknown
        + b"\x1f\x43\xb6\x75"
        + unknown
        + cluster_time
        + block
    )


async def _post(
    client: httpx.AsyncClient,
    data: bytes,
    content_type: str,
    *,
    user_id: str | None = None,
    filename: str = "voice",
) -> httpx.Response:
    headers = {"X-User-Id": user_id} if user_id else {}
    files = {"audio": (filename, data, content_type)}
    return await client.post("/api/stt", files=files, headers=headers)


# --- Длительность записи ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "content_type", "expected"),
    [
        ("chrome_2s.webm", "audio/webm", 1.92),
        ("chrome_2s_opus.mp4", "audio/mp4", 1.94),
        ("aac_2s_fragmented.mp4", "audio/mp4", 2.0),
        ("opus_2s.ogg", "audio/ogg", 2.0),
    ],
)
def test_duration_of_browser_recordings(name: str, content_type: str, expected: float) -> None:
    seconds = duration_seconds(_fixture(name), content_type)
    assert seconds == pytest.approx(expected, abs=0.05)


def test_duration_of_generated_files() -> None:
    assert duration_seconds(_wav(31.5), "audio/wav") == pytest.approx(31.5)
    assert duration_seconds(_webm(35_000), "audio/webm") == pytest.approx(35.0)
    assert duration_seconds(b"\x1a\x45\xdf\xa3" + b"\x00" * 50, "audio/webm") is None


# --- Успешный ответ -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "content_type"),
    [
        ("chrome_2s.webm", "audio/webm;codecs=opus"),
        ("chrome_2s_opus.mp4", "audio/mp4;codecs=opus"),
        ("aac_2s_fragmented.mp4", "audio/mp4"),
        ("opus_2s.ogg", "audio/ogg; codecs=opus"),
    ],
)
async def test_recognized_text(
    client: httpx.AsyncClient, calls: list, name: str, content_type: str
) -> None:
    audio = _fixture(name)
    response = await _post(client, audio, content_type)

    assert response.status_code == 200
    assert response.json() == {"text": PHRASE}
    # Запись уходит провайдеру как есть, без перекодировки; формат — без параметров кодека.
    assert calls == [(audio, content_type.split(";")[0])]
    assert response.headers["X-User-Id"]  # без заголовка — новый пользователь, как в /api/chat


async def test_wav_is_accepted(client: httpx.AsyncClient, calls: list) -> None:
    response = await _post(client, _wav(3), "audio/wav")
    assert response.status_code == 200


# --- Ошибки -------------------------------------------------------------------------------


def _assert_error(response: httpx.Response, code: int) -> None:
    assert response.status_code == code
    body = response.json()
    assert list(body) == ["detail"]
    assert isinstance(body["detail"], str) and body["detail"]  # текст для пользователя


async def test_bad_user_id_400(client: httpx.AsyncClient, calls: list) -> None:
    audio = _fixture("chrome_2s.webm")
    response = await _post(client, audio, "audio/webm", user_id="not-a-uuid")
    _assert_error(response, 400)
    assert calls == []


@pytest.mark.parametrize("seconds", [31.5, 45])
async def test_too_long_wav_413(client: httpx.AsyncClient, calls: list, seconds: float) -> None:
    _assert_error(await _post(client, _wav(seconds), "audio/wav"), 413)
    assert calls == []


async def test_too_long_webm_413(client: httpx.AsyncClient, calls: list) -> None:
    _assert_error(await _post(client, _webm(35_000), "audio/webm"), 413)
    assert calls == []


async def test_slightly_over_30_seconds_is_accepted(client: httpx.AsyncClient, calls: list) -> None:
    """Интерфейс останавливает запись на 30-й секунде, файл выходит чуть длиннее."""
    response = await _post(client, _webm(30_400), "audio/webm")
    assert response.status_code == 200


async def test_unreadable_duration_falls_back_to_size(
    client: httpx.AsyncClient, calls: list
) -> None:
    """Длительность не прочиталась — ограничение по размеру файла."""
    small = b"OggS" + b"\x00" * 1000
    large = b"OggS" + b"\x00" * stt_route.MAX_BYTES_WITHOUT_DURATION
    assert (await _post(client, small, "audio/ogg")).status_code == 200
    _assert_error(await _post(client, large, "audio/ogg"), 413)


async def test_file_over_upload_limit_413(client: httpx.AsyncClient, calls: list) -> None:
    huge = _wav(1) + b"\x00" * stt_route.MAX_UPLOAD_BYTES
    _assert_error(await _post(client, huge, "audio/wav"), 413)


@pytest.mark.parametrize(
    "content_type", ["text/plain", "video/webm", "audio/mpeg", "application/octet-stream"]
)
async def test_unsupported_type_415(
    client: httpx.AsyncClient, calls: list, content_type: str
) -> None:
    audio = _fixture("chrome_2s.webm")
    _assert_error(await _post(client, audio, content_type), 415)
    assert calls == []


async def test_empty_audio_415(client: httpx.AsyncClient, calls: list) -> None:
    _assert_error(await _post(client, b"", "audio/webm"), 415)


async def test_missing_audio_field_415(client: httpx.AsyncClient, calls: list) -> None:
    response = await client.post("/api/stt", files={"other": ("x", b"1", "audio/webm")})
    _assert_error(response, 415)
    _assert_error(await client.post("/api/stt", json={"audio": "x"}), 415)


async def test_not_audio_with_audio_type_415(client: httpx.AsyncClient, calls: list) -> None:
    _assert_error(await _post(client, b"%PDF-1.7 " * 100, "audio/webm"), 415)
    assert calls == []


async def test_no_speech_422(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def silence(audio: bytes, content_type: str) -> str:
        return ""

    monkeypatch.setattr(stt_route, "transcribe", silence)
    audio = _fixture("chrome_2s.webm")
    response = await _post(client, audio, "audio/webm")
    _assert_error(response, 422)
    assert response.json()["detail"] == "Не расслышал, повторите, пожалуйста."


async def test_too_short_422_without_provider(client: httpx.AsyncClient, calls: list) -> None:
    _assert_error(await _post(client, _wav(0.1), "audio/wav"), 422)
    assert calls == []


async def test_rate_limit_429_per_user(client: httpx.AsyncClient, calls: list) -> None:
    audio = _fixture("chrome_2s.webm")
    user, other = str(uuid4()), str(uuid4())
    for _ in range(stt_route.RATE_LIMIT_REQUESTS):
        assert (await _post(client, audio, "audio/webm", user_id=user)).status_code == 200

    limited = await _post(client, audio, "audio/webm", user_id=user)
    _assert_error(limited, 429)
    assert int(limited.headers["Retry-After"]) > 0
    # Лимит — на пользователя: у другого запросы идут.
    assert (await _post(client, audio, "audio/webm", user_id=other)).status_code == 200


def test_rate_limiter_window() -> None:
    now = [0.0]
    limiter = stt_route.RateLimiter(2, 60, clock=lambda: now[0])
    assert limiter.hit("u") is None
    assert limiter.hit("u") is None
    assert limiter.hit("u") == pytest.approx(60)
    now[0] = 30.0
    assert limiter.hit("u") == pytest.approx(30)  # отклонённые запросы окно не продлевают
    now[0] = 60.0
    assert limiter.hit("u") is None


async def test_provider_unavailable_503(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(audio: bytes, content_type: str) -> str:
        raise STTUnavailableError("таймаут")

    monkeypatch.setattr(stt_route, "transcribe", down)
    audio = _fixture("chrome_2s.webm")
    _assert_error(await _post(client, audio, "audio/webm"), 503)


async def test_no_key_503(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Настоящий клиент без ключа: 503 ещё до сети."""
    monkeypatch.delenv("STT_API_KEY", raising=False)
    monkeypatch.setenv("STT_MODEL", "gemini-test")
    audio = _fixture("chrome_2s.webm")
    _assert_error(await _post(client, audio, "audio/webm"), 503)


def test_openapi_shows_file_field_and_codes() -> None:
    operation = app.openapi()["paths"]["/api/stt"]["post"]
    assert set(operation["responses"]) >= {"200", "400", "413", "415", "422", "429", "503"}
    assert "multipart/form-data" in operation["requestBody"]["content"]


# --- Клиент Gemini (сеть подменена) -------------------------------------------------------


def _gemini(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    monkeypatch.setenv("STT_API_KEY", "test-key")
    monkeypatch.setenv("STT_MODEL", "gemini-test")
    monkeypatch.delenv("STT_THINKING_LEVEL", raising=False)
    real_client = httpx.AsyncClient

    def client_with_mock(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(stt_client.httpx, "AsyncClient", client_with_mock)


def _answer(text: str) -> dict:
    parts = [{"text": json.dumps({"text": text}, ensure_ascii=False)}]
    return {"candidates": [{"content": {"parts": parts}}]}


async def test_gemini_request_and_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_answer(f"  {PHRASE} "))

    _gemini(monkeypatch, handler)
    audio = _fixture("aac_2s_fragmented.mp4")

    assert await stt_client.transcribe(audio, "audio/mp4") == PHRASE

    request = seen[0]
    assert request.url.path.endswith("/models/gemini-test:generateContent")
    assert request.headers["x-goog-api-key"] == "test-key"
    assert "key=" not in str(request.url)  # ключ не в адресе — не попадёт в логи
    body = json.loads(request.content)
    inline = body["contents"][0]["parts"][0]["inlineData"]
    assert inline["mimeType"] == "audio/m4a"
    assert base64.b64decode(inline["data"]) == audio
    # STT_THINKING_LEVEL пустой — уровень обдумывания не передаётся, решает модель.
    assert "thinkingConfig" not in body["generationConfig"]


async def test_gemini_thinking_level_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_answer(PHRASE))

    _gemini(monkeypatch, handler)
    monkeypatch.setenv("STT_THINKING_LEVEL", " minimal ")

    await stt_client.transcribe(b"x", "audio/webm")

    config = json.loads(seen[0].content)["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingLevel": "minimal"}


@pytest.mark.parametrize(
    "payload",
    [
        _answer(""),
        _answer("   "),
        {"candidates": []},
        {"promptFeedback": {"blockReason": "OTHER"}},
        {"candidates": [{"finishReason": "SAFETY"}]},
    ],
)
async def test_gemini_no_speech_is_empty(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    _gemini(monkeypatch, lambda request: httpx.Response(200, json=payload))
    assert await stt_client.transcribe(b"x", "audio/webm") == ""


async def test_gemini_plain_text_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"candidates": [{"content": {"parts": [{"text": PHRASE}]}}]}
    _gemini(monkeypatch, lambda request: httpx.Response(200, json=payload))
    assert await stt_client.transcribe(b"x", "audio/webm") == PHRASE


@pytest.mark.parametrize("code", [400, 403, 429, 500, 503])
async def test_gemini_error_is_unavailable(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    _gemini(monkeypatch, lambda request: httpx.Response(code, json={"error": {}}))
    with pytest.raises(STTUnavailableError):
        await stt_client.transcribe(b"x", "audio/webm")


async def test_gemini_network_error_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    _gemini(monkeypatch, handler)
    with pytest.raises(STTUnavailableError):
        await stt_client.transcribe(b"x", "audio/webm")


async def test_gemini_needs_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STT_API_KEY", "test-key")
    monkeypatch.delenv("STT_MODEL", raising=False)
    with pytest.raises(STTUnavailableError):
        await stt_client.transcribe(b"x", "audio/webm")
