import asyncio

from pydantic import BaseModel

from app.agent.loop import AgentRunner
from app.agent.models import AssistantTurn, ModelMessage, ToolCall
from app.agent.permissions import InMemoryCheckpointStore, InMemoryConfirmationStore
from app.agent.tools import ToolRegistry


class OrderInput(BaseModel):
    symbol: str
    quantity: str


class OrderProvider:
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
                        id="order-call",
                        name="preview_order",
                        arguments={"symbol": "BTCUSDT", "quantity": "0.01"},
                    )
                ]
            )
        assert any(
            message.role == "tool" and "accepted" in message.content
            for message in messages
        )
        return AssistantTurn(content="模拟订单已经执行。")


def test_agent_pauses_for_confirmation_and_resumes_the_same_run() -> None:
    executions: list[OrderInput] = []
    registry = ToolRegistry()

    async def preview_order(arguments: OrderInput) -> dict[str, str]:
        executions.append(arguments)
        return {"status": "accepted"}

    registry.register(
        name="preview_order",
        description="Execute a simulated order",
        input_model=OrderInput,
        handler=preview_order,
        permission="simulate",
    )
    confirmations = InMemoryConfirmationStore()
    checkpoints = InMemoryCheckpointStore()
    runner = AgentRunner(
        provider=OrderProvider(),
        tools=registry,
        confirmations=confirmations,
        checkpoints=checkpoints,
    )

    async def run_and_resume():
        first_events = [
            event
            async for event in runner.stream(
                user_message="模拟买入 0.01 BTC",
                system_prompt="test",
            )
        ]
        confirmation_id = first_events[-2].data["confirmation_id"]
        await confirmations.approve(confirmation_id)
        resumed_events = [event async for event in runner.resume(confirmation_id)]
        return first_events, resumed_events

    first_events, resumed_events = asyncio.run(run_and_resume())

    assert executions == [OrderInput(symbol="BTCUSDT", quantity="0.01")]
    assert [event.type for event in first_events[-2:]] == [
        "confirmation_required",
        "run_paused",
    ]
    assert resumed_events[0].type == "run_resumed"
    assert resumed_events[-1].type == "run_completed"
    assert resumed_events[0].run_id == first_events[0].run_id
    assert resumed_events[0].sequence == first_events[-1].sequence + 1


def test_prohibited_tool_can_never_execute() -> None:
    executed = False
    registry = ToolRegistry()

    async def withdraw(arguments: OrderInput) -> dict[str, str]:
        nonlocal executed
        executed = True
        return {"status": "sent"}

    registry.register(
        name="withdraw",
        description="Withdraw assets",
        input_model=OrderInput,
        handler=withdraw,
        permission="prohibited",
    )

    result = asyncio.run(
        registry.execute(
            "withdraw",
            {"symbol": "BTC", "quantity": "1"},
            confirmed=True,
        )
    )

    assert executed is False
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "tool_prohibited"
