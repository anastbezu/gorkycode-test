"""Смоук-тест API (backend-02b): `/health` отвечает 200, когда база доступна."""

import httpx
import pytest
from sqlalchemy import Engine

from main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_health_ok(engine: Engine) -> None:
    # Фикстура engine поднимает схему в тестовой базе и задаёт DATABASE_URL;
    # без базы тест пропускается, как остальные тесты с БД.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "connected"}
