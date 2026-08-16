import asyncio

from app.agent.loop import AgentRunner
from app.agent.models import AssistantTurn, StreamChunk
from app.agent.tools import ToolRegistry


class StreamingProvider:
    def __init__(self) -> None:
        self.deltas = ["BTC", " 当前", " 63000"]

    async def stream(self, messages, tools):
        for delta in self.deltas:
            yield StreamChunk(content_delta=delta)
        yield StreamChunk(final_turn=AssistantTurn(content="".join(self.deltas)))


class StreamingToolProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            yield StreamChunk(
                final_turn=AssistantTurn(
                    content="",
                    tool_calls=[
                        __import__("app.agent.models", fromlist=["ToolCall"]).ToolCall(
                            id="call-1", name="noop", arguments={}
                        )
                    ],
                )
            )
        else:
            yield StreamChunk(content_delta="完成")
            yield StreamChunk(final_turn=AssistantTurn(content="完成"))


def test_streaming_provider_emits_token_by_token() -> None:
    async def exercise():
        registry = ToolRegistry()
        runner = AgentRunner(provider=StreamingProvider(), tools=registry)
        deltas: list[str] = []
        completed = False
        async for event in runner.stream(user_message="BTC 价格", system_prompt="test"):
            if event.type == "answer_delta":
                deltas.append(event.data["content"])
            if event.type == "run_completed":
                completed = True
        return deltas, completed

    deltas, completed = asyncio.run(exercise())

    assert deltas == ["BTC", " 当前", " 63000"]
    assert completed is True


def test_streaming_tool_calls_are_handled() -> None:
    async def exercise():
        registry = ToolRegistry()

        async def noop(_):
            return {"ok": True}

        from pydantic import BaseModel

        class Empty(BaseModel):
            pass

        registry.register(
            name="noop",
            description="noop",
            input_model=Empty,
            handler=noop,
        )
        runner = AgentRunner(provider=StreamingToolProvider(), tools=registry)
        events = []
        async for event in runner.stream(user_message="go", system_prompt="test"):
            events.append(event.type)
        return events

    events = asyncio.run(exercise())

    assert "tool_started" in events
    assert "tool_finished" in events
    assert "run_completed" in events
