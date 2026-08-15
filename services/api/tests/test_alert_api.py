import asyncio
from uuid import uuid4

import httpx

from app.main import app


def test_alert_api_creates_lists_pauses_and_resumes_a_task() -> None:
    owner_id = f"api-owner-{uuid4()}"

    async def exercise_api():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            created = await client.post(
                "/api/alerts",
                json={
                    "owner_id": owner_id,
                    "market": "spot",
                    "symbol": "BTCUSDT",
                    "condition": "price_below",
                    "threshold": "65000",
                },
            )
            task_id = created.json()["id"]
            listed = await client.get("/api/alerts", params={"owner_id": owner_id})
            paused = await client.post(
                f"/api/alerts/{task_id}/pause", params={"owner_id": owner_id}
            )
            resumed = await client.post(
                f"/api/alerts/{task_id}/resume", params={"owner_id": owner_id}
            )
            return created, listed, paused, resumed

    created, listed, paused, resumed = asyncio.run(exercise_api())

    assert created.status_code == 201
    assert listed.json()[0]["symbol"] == "BTCUSDT"
    assert paused.json()["status"] == "paused"
    assert resumed.json()["status"] == "active"


def test_alert_api_does_not_expose_another_owners_task() -> None:
    async def exercise_api():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            created = await client.post(
                "/api/alerts",
                json={
                    "owner_id": "owner-secret",
                    "market": "spot",
                    "symbol": "ETHUSDT",
                    "condition": "price_above",
                    "threshold": "4000",
                },
            )
            return await client.post(
                f"/api/alerts/{created.json()['id']}/pause",
                params={"owner_id": "different-owner"},
            )

    response = asyncio.run(exercise_api())

    assert response.status_code == 404
