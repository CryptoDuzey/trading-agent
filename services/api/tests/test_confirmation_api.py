import asyncio
import json

import httpx
from pydantic import BaseModel

import app.main as main_module
from app.agent.loop import AgentRunner
from app.agent.models import AssistantTurn, ModelMessage, ToolCall
from app.agent.tools import ToolRegistry


class SimulationInput(BaseModel):
    symbol: str


class SimulationProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        messages: list[ModelMessage],
        tools: list[dict[str, object]],
    ) -> AssistantTurn:
        self.calls += 1
        if self.calls == 1:
            return AssistantTurn(
                tool_calls=[
                    ToolCall(
                        id="simulate-1",
                        name="simulate_order",
                        arguments={"symbol": "BTCUSDT"},
                    )
                ]
            )
        return AssistantTurn(content="simulation finished")


def test_confirmation_endpoint_resumes_a_paused_agent_run(monkeypatch) -> None:
    registry = ToolRegistry()

    async def simulate_order(arguments: SimulationInput) -> dict[str, str]:
        return {"status": "simulated", "symbol": arguments.symbol}

    registry.register(
        name="simulate_order",
        description="Run a simulated order",
        input_model=SimulationInput,
        handler=simulate_order,
        permission="simulate",
    )
    runner = AgentRunner(provider=SimulationProvider(), tools=registry)
    monkeypatch.setattr(main_module, "build_agent_runner", lambda: runner)

    async def make_requests():
        transport = httpx.ASGITransport(app=main_module.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            first = await client.post(
                "/api/chat/stream",
                json={"message": "simulate BTC", "session_id": "confirm-session"},
            )
            confirmation_event = next(
                json.loads(line.removeprefix("data: "))
                for line in first.text.splitlines()
                if line.startswith("data: ") and '"confirmation_required"' in line
            )
            confirmation_id = confirmation_event["data"]["confirmation_id"]
            resumed = await client.post(f"/api/confirmations/{confirmation_id}/approve")
            return first, resumed

    first, resumed = asyncio.run(make_requests())

    assert first.status_code == 200
    assert '"type": "run_paused"' in first.text
    assert resumed.status_code == 200
    assert '"type": "run_resumed"' in resumed.text
    assert "simulation finished" in resumed.text
    assert '"type": "run_completed"' in resumed.text
