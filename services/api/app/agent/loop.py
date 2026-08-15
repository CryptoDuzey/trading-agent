import json
from collections.abc import AsyncIterator
from typing import Protocol
from uuid import uuid4

from app.agent.models import AgentEvent, AssistantTurn, ModelMessage
from app.agent.tools import ToolRegistry


class ModelProvider(Protocol):
    async def complete(
        self,
        messages: list[ModelMessage],
        tools: list[dict[str, object]],
    ) -> AssistantTurn: ...


class AgentRunner:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        tools: ToolRegistry,
        max_steps: int = 8,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.provider = provider
        self.tools = tools
        self.max_steps = max_steps

    async def stream(
        self,
        *,
        user_message: str,
        system_prompt: str,
        history: list[ModelMessage] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        run_id = str(uuid4())
        sequence = 0
        messages = [
            ModelMessage(role="system", content=system_prompt),
            *(history or []),
            ModelMessage(role="user", content=user_message),
        ]

        def event(
            event_type: str,
            *,
            step: int = 0,
            data: dict[str, object] | None = None,
        ) -> AgentEvent:
            nonlocal sequence
            sequence += 1
            return AgentEvent(
                type=event_type,  # type: ignore[arg-type]
                run_id=run_id,
                sequence=sequence,
                step=step,
                data=data or {},
            )

        yield event("run_started", data={"user_message": user_message})

        for step in range(1, self.max_steps + 1):
            yield event("model_started", step=step)
            try:
                turn = await self.provider.complete(
                    messages=messages,
                    tools=self.tools.definitions(),
                )
            except Exception as error:  # noqa: BLE001 - provider boundary
                yield event(
                    "run_failed",
                    step=step,
                    data={"code": "model_error", "message": str(error)},
                )
                return

            if turn.tool_calls:
                messages.append(
                    ModelMessage(
                        role="assistant",
                        content=turn.content,
                        tool_calls=turn.tool_calls,
                    )
                )
                for call in turn.tool_calls:
                    yield event(
                        "tool_started",
                        step=step,
                        data={
                            "tool_call_id": call.id,
                            "name": call.name,
                            "arguments": call.arguments,
                        },
                    )
                    result = await self.tools.execute(call.name, call.arguments)
                    yield event(
                        "tool_finished",
                        step=step,
                        data={
                            "tool_call_id": call.id,
                            "name": call.name,
                            **result.model_dump(mode="json"),
                        },
                    )
                    messages.append(
                        ModelMessage(
                            role="tool",
                            name=call.name,
                            tool_call_id=call.id,
                            content=json.dumps(
                                result.model_dump(mode="json"),
                                ensure_ascii=False,
                            ),
                        )
                    )
                continue

            if not turn.content.strip():
                yield event(
                    "run_failed",
                    step=step,
                    data={
                        "code": "empty_model_response",
                        "message": "Model returned neither content nor tool calls",
                    },
                )
                return

            yield event(
                "answer_delta",
                step=step,
                data={"content": turn.content},
            )
            yield event("run_completed", step=step)
            return

        yield event(
            "run_failed",
            step=self.max_steps,
            data={
                "code": "max_steps_exceeded",
                "message": "Agent stopped before reaching a final answer",
            },
        )
