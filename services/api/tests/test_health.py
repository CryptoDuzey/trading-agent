import asyncio

import httpx
import pytest


def test_health_endpoint_reports_service_is_ready() -> None:
    try:
        from app.main import app
    except ModuleNotFoundError:
        pytest.fail("FastAPI 应用尚未实现")

    async def make_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get("/health")

    response = asyncio.run(make_request())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "lobster-api",
    }

