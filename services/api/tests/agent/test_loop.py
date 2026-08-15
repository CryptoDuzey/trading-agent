import asyncio

from pydantic import BaseModel

from app.agent.loop import AgentRunner
from app.agent.models import AssistantTurn, ModelMessage, ToolCall
from app.agent.tools import ToolRegistry


class QuoteInput(BaseModel):
    symbol: str


class ScriptedProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.received_messages: list[list[ModelMessage]] = []

    async def complete(
        self,
        messages: list[ModelMessage],
        tools: list[dict[str, object]],
    ) -> AssistantTurn:
        self.calls += 1
        self.received_messages.append(messages.copy())

        if self.calls == 1:
            assert tools[0]["name"] == "get_quote"
            return AssistantTurn(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="get_quote",
                        arguments={"symbol": "BTCUSDT"},
                    )
                ]
            )

        assert any(
            message.role == "tool" and "68000" in message.content
            for message in messages
        )
        return AssistantTurn(content="BTCUSDT 的测试价格是 68000。")


def test_agent_calls_a_tool_observes_the_result_and_finishes() -> None:
    provider = ScriptedProvider()
    registry = ToolRegistry()

    async def get_quote(arguments: QuoteInput) -> dict[str, float | str]:
        return {"symbol": arguments.symbol, "price": 68000.0}

    registry.register(
        name="get_quote",
        description="Get a current market quote",
        input_model=QuoteInput,
        handler=get_quote,
    )
    runner = AgentRunner(provider=provider, tools=registry, max_steps=4)

    async def collect_events():
        return [
            event
            async for event in runner.stream(
                user_message="现在 BTC 多少钱？",
                system_prompt="Use tools for live market data.",
            )
        ]

    events = asyncio.run(collect_events())

    assert [event.type for event in events] == [
        "run_started",
        "model_started",
        "tool_started",
        "tool_finished",
        "model_started",
        "answer_delta",
        "run_completed",
    ]
    assert events[3].data["ok"] is True
    assert events[-2].data["content"] == "BTCUSDT 的测试价格是 68000。"
    assert provider.calls == 2


class EndlessToolProvider:
    async def complete(
        self,
        messages: list[ModelMessage],
        tools: list[dict[str, object]],
    ) -> AssistantTurn:
        return AssistantTurn(
            tool_calls=[ToolCall(id="loop", name="missing_tool", arguments={})]
        )


def test_agent_stops_after_the_maximum_number_of_steps() -> None:
    runner = AgentRunner(
        provider=EndlessToolProvider(),
        tools=ToolRegistry(),
        max_steps=2,
    )

    async def collect_events():
        return [
            event
            async for event in runner.stream(
                user_message="keep going",
                system_prompt="test",
            )
        ]

    events = asyncio.run(collect_events())

    assert events[-1].type == "run_failed"
    assert events[-1].data["code"] == "max_steps_exceeded"


class CapturingProvider:
    def __init__(self) -> None:
        self.messages: list[ModelMessage] = []

    async def complete(
        self,
        messages: list[ModelMessage],
        tools: list[dict[str, object]],
    ) -> AssistantTurn:
        self.messages = messages.copy()
        return AssistantTurn(content="context received")


def test_agent_places_recent_conversation_before_the_new_user_message() -> None:
    provider = CapturingProvider()
    runner = AgentRunner(provider=provider, tools=ToolRegistry())
    history = [
        ModelMessage(role="user", content="I trade spot only."),
        ModelMessage(role="assistant", content="Understood."),
    ]

    async def collect_events():
        return [
            event
            async for event in runner.stream(
                user_message="What market do I trade?",
                system_prompt="test",
                history=history,
            )
        ]

    asyncio.run(collect_events())

    assert [message.role for message in provider.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert provider.messages[-1].content == "What market do I trade?"
