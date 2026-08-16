import asyncio
import json

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
        "service": "trading-agent",
    }


def test_chat_endpoint_streams_agent_events_and_a_safe_fallback_reply() -> None:
    from app.main import app

    async def make_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/api/chat/stream",
                json={
                    "message": "分析 BTC 当前走势",
                    "session_id": "test-agent-session",
                },
            )

    response = asyncio.run(make_request())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: session" in response.text
    assert "test-agent-session" in response.text
    assert "event: agent_event" in response.text
    assert '"type": "run_started"' in response.text
    assert "event: delta" in response.text
    assert "尚未配置 DEEPSEEK_API_KEY" in response.text
    assert "event: done" in response.text

    from app.agent.runtime import conversation_store

    history = asyncio.run(conversation_store.get_recent("test-agent-session"))
    assert [message.role for message in history] == ["user", "assistant"]

    run_started = next(
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and '"run_started"' in line
    )

    async def get_trace() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get(f"/api/runs/{run_started['run_id']}")

    trace_response = asyncio.run(get_trace())
    assert trace_response.status_code == 200
    assert trace_response.json()["status"] == "completed"
    assert trace_response.json()["events"][0]["type"] == "run_started"


def test_chat_endpoint_rejects_a_blank_message() -> None:
    from app.main import app

    async def make_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/chat/stream", json={"message": "   "})

    response = asyncio.run(make_request())

    assert response.status_code == 422
