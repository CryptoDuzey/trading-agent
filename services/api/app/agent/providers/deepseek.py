import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.agent.models import (
    AssistantTurn,
    ModelMessage,
    StreamChunk,
    TokenUsage,
    ToolCall,
)


class DeepSeekProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("DeepSeek API key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client

    async def complete(
        self,
        messages: list[ModelMessage],
        tools: list[dict[str, object]],
    ) -> AssistantTurn:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_payload(message) for message in messages],
            "stream": False,
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": tool} for tool in tools
            ]
            payload["tool_choice"] = "auto"

        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            return self._parse_response(response.json())
        finally:
            if owns_client:
                await client.aclose()

    async def stream(
        self,
        messages: list[ModelMessage],
        tools: list[dict[str, object]],
    ) -> AsyncIterator[StreamChunk]:
        """Stream the completion token by token, then emit the assembled turn."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_payload(message) for message in messages],
            "stream": True,
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": tool} for tool in tools
            ]
            payload["tool_choice"] = "auto"

        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            ) as response:
                response.raise_for_status()
                content_parts: list[str] = []
                tool_call_slots: dict[int, dict[str, str]] = {}
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    chunk = json.loads(data)
                    choices = chunk.get("choices") or []
                    delta = choices[0].get("delta") or {} if choices else {}
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                        yield StreamChunk(content_delta=delta["content"])
                    for raw_call in delta.get("tool_calls") or []:
                        index = raw_call.get("index", 0)
                        slot = tool_call_slots.setdefault(
                            index, {"id": "", "name": "", "arguments": ""}
                        )
                        if raw_call.get("id"):
                            slot["id"] = raw_call["id"]
                        function = raw_call.get("function") or {}
                        if function.get("name"):
                            slot["name"] += function["name"]
                        if function.get("arguments"):
                            slot["arguments"] += function["arguments"]

                tool_calls: list[ToolCall] = []
                for index in sorted(tool_call_slots):
                    slot = tool_call_slots[index]
                    if not slot["name"]:
                        continue
                    try:
                        arguments = json.loads(slot["arguments"] or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                    tool_calls.append(
                        ToolCall(
                            id=slot["id"] or f"call-{index}",
                            name=slot["name"],
                            arguments=arguments,
                        )
                    )
                yield StreamChunk(
                    final_turn=AssistantTurn(
                        content="".join(content_parts),
                        tool_calls=tool_calls,
                    )
                )
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _message_payload(message: ModelMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }
        if message.role == "assistant" and message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                        ),
                    },
                }
                for call in message.tool_calls
            ]
        if message.role == "tool":
            payload["tool_call_id"] = message.tool_call_id
        return payload

    @staticmethod
    def _parse_response(payload: dict[str, Any]) -> AssistantTurn:
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("DeepSeek returned an invalid response") from error

        tool_calls: list[ToolCall] = []
        for raw_call in message.get("tool_calls") or []:
            function = raw_call["function"]
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"DeepSeek returned invalid tool arguments for {function['name']}"
                ) from error
            if not isinstance(arguments, dict):
                raise TypeError("Tool arguments must be a JSON object")
            tool_calls.append(
                ToolCall(
                    id=raw_call["id"],
                    name=function["name"],
                    arguments=arguments,
                )
            )

        usage_payload = payload.get("usage")
        usage = TokenUsage.model_validate(usage_payload) if usage_payload else None
        return AssistantTurn(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            usage=usage,
        )
