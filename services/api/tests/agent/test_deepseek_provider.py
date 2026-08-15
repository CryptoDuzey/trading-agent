import asyncio
import json

import httpx

from app.agent.models import ModelMessage, ToolCall
from app.agent.providers.deepseek import DeepSeekProvider


def test_deepseek_provider_translates_messages_tools_and_tool_calls() -> None:
    async def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["messages"] == [
            {"role": "system", "content": "Use market tools."},
            {"role": "user", "content": "BTC price?"},
        ]
        assert payload["tools"][0]["function"]["name"] == "get_quote"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-quote",
                                    "type": "function",
                                    "function": {
                                        "name": "get_quote",
                                        "arguments": '{"symbol":"BTCUSDT"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 8,
                    "total_tokens": 28,
                },
            },
        )

    async def call_provider():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handle_request),
            base_url="https://api.deepseek.com",
        )
        provider = DeepSeekProvider(api_key="test-key", client=client)
        try:
            return await provider.complete(
                messages=[
                    ModelMessage(role="system", content="Use market tools."),
                    ModelMessage(role="user", content="BTC price?"),
                ],
                tools=[
                    {
                        "name": "get_quote",
                        "description": "Get a current quote",
                        "parameters": {
                            "type": "object",
                            "properties": {"symbol": {"type": "string"}},
                        },
                    }
                ],
            )
        finally:
            await client.aclose()

    turn = asyncio.run(call_provider())

    assert turn.content == ""
    assert turn.tool_calls == [
        ToolCall(
            id="call-quote",
            name="get_quote",
            arguments={"symbol": "BTCUSDT"},
        )
    ]
    assert turn.usage is not None
    assert turn.usage.total_tokens == 28


def test_deepseek_provider_returns_a_final_answer() -> None:
    async def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "No current data is available.",
                        }
                    }
                ]
            },
        )

    async def call_provider():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        provider = DeepSeekProvider(api_key="test-key", client=client)
        try:
            return await provider.complete(
                messages=[ModelMessage(role="user", content="BTC price?")],
                tools=[],
            )
        finally:
            await client.aclose()

    turn = asyncio.run(call_provider())

    assert turn.content == "No current data is available."
    assert turn.tool_calls == []
