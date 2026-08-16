from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from app.agent.context import ContextManager
from app.agent.models import AgentEvent, AssistantTurn, ModelMessage, ToolCall
from app.agent.permissions import (
    InMemoryCheckpointStore,
    InMemoryConfirmationStore,
    RunCheckpoint,
)
from app.agent.tools import ToolRegistry


class ModelProvider(Protocol):
    async def complete(
        self,
        messages: list[ModelMessage],
        tools: list[dict[str, object]],
    ) -> AssistantTurn: ...


@dataclass
class _RunState:
    run_id: str
    messages: list[ModelMessage]
    sequence: int = 0
    paused: bool = False


class AgentRunner:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        tools: ToolRegistry,
        max_steps: int = 8,
        context: ContextManager | None = None,
        confirmations: InMemoryConfirmationStore | None = None,
        checkpoints: InMemoryCheckpointStore | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.provider = provider
        self.tools = tools
        self.max_steps = max_steps
        self.context = context or ContextManager()
        self.confirmations = confirmations or InMemoryConfirmationStore()
        self.checkpoints = checkpoints or InMemoryCheckpointStore()

    async def stream(
        self,
        *,
        user_message: str,
        system_prompt: str,
        history: list[ModelMessage] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        state = _RunState(
            run_id=str(uuid4()),
            messages=[
                ModelMessage(role="system", content=system_prompt),
                *self.context.select_history(history or []),
                ModelMessage(role="user", content=user_message),
            ],
        )
        yield self._event(
            state,
            "run_started",
            data={"user_message": user_message},
        )
        async for event in self._run_steps(state, start_step=1):
            yield event

    async def resume(self, confirmation_id: str) -> AsyncIterator[AgentEvent]:
        checkpoint = await self.checkpoints.get(confirmation_id)
        if checkpoint is None or not checkpoint.pending_calls:
            raise ValueError("Confirmation checkpoint was not found")

        confirmed_call = checkpoint.pending_calls[0]
        await self.confirmations.consume(
            confirmation_id,
            run_id=checkpoint.run_id,
            tool_call=confirmed_call,
        )
        await self.checkpoints.delete(confirmation_id)

        state = _RunState(
            run_id=checkpoint.run_id,
            sequence=checkpoint.sequence,
            messages=[message.model_copy(deep=True) for message in checkpoint.messages],
        )
        yield self._event(
            state,
            "run_resumed",
            step=checkpoint.step,
            data={"confirmation_id": confirmation_id},
        )
        async for event in self._process_tool_calls(
            state,
            checkpoint.pending_calls,
            step=checkpoint.step,
            confirmed_call_id=confirmed_call.id,
        ):
            yield event
        if state.paused:
            return
        async for event in self._run_steps(
            state,
            start_step=checkpoint.step + 1,
        ):
            yield event

    async def _run_steps(
        self,
        state: _RunState,
        *,
        start_step: int,
    ) -> AsyncIterator[AgentEvent]:
        for step in range(start_step, self.max_steps + 1):
            yield self._event(state, "model_started", step=step)
            try:
                turn: AssistantTurn | None = None
                async for item in self._complete_step(state, step):
                    if isinstance(item, AssistantTurn):
                        turn = item
                    else:
                        yield item
                if turn is None:
                    turn = AssistantTurn()
            except Exception as error:  # noqa: BLE001 - provider boundary
                yield self._event(
                    state,
                    "run_failed",
                    step=step,
                    data={"code": "model_error", "message": str(error)},
                )
                return

            if turn.tool_calls:
                state.messages.append(
                    ModelMessage(
                        role="assistant",
                        content=turn.content,
                        tool_calls=turn.tool_calls,
                    )
                )
                async for event in self._process_tool_calls(
                    state,
                    turn.tool_calls,
                    step=step,
                ):
                    yield event
                if state.paused:
                    return
                continue

            if not turn.content.strip():
                yield self._event(
                    state,
                    "run_failed",
                    step=step,
                    data={
                        "code": "empty_model_response",
                        "message": "Model returned neither content nor tool calls",
                    },
                )
                return

            if not hasattr(self.provider, "stream"):
                yield self._event(
                    state,
                    "answer_delta",
                    step=step,
                    data={"content": turn.content},
                )
            yield self._event(state, "run_completed", step=step)
            return

        yield self._event(
            state,
            "run_failed",
            step=self.max_steps,
            data={
                "code": "max_steps_exceeded",
                "message": "Agent stopped before reaching a final answer",
            },
        )

    async def _complete_step(
        self,
        state: _RunState,
        step: int,
    ) -> AsyncIterator[AgentEvent | AssistantTurn]:
        """Call the model, streaming token deltas as answer events when possible."""
        stream = getattr(self.provider, "stream", None)
        if stream is None:
            yield await self.provider.complete(
                messages=state.messages,
                tools=self.tools.definitions(),
            )
            return

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        async for chunk in stream(
            messages=state.messages,
            tools=self.tools.definitions(),
        ):
            if chunk.reasoning_delta:
                reasoning_parts.append(chunk.reasoning_delta)
                yield self._event(
                    state,
                    "reasoning_delta",
                    step=step,
                    data={"content": chunk.reasoning_delta},
                )
            if chunk.content_delta:
                content_parts.append(chunk.content_delta)
                yield self._event(
                    state,
                    "answer_delta",
                    step=step,
                    data={"content": chunk.content_delta},
                )
            if chunk.final_turn is not None:
                turn = chunk.final_turn
                if not turn.content and content_parts:
                    turn = turn.model_copy(
                        update={"content": "".join(content_parts)}
                    )
                if not turn.reasoning and reasoning_parts:
                    turn = turn.model_copy(
                        update={"reasoning": "".join(reasoning_parts)}
                    )
                yield turn
                return
        yield AssistantTurn(content="".join(content_parts))

    async def _process_tool_calls(
        self,
        state: _RunState,
        calls: list[ToolCall],
        *,
        step: int,
        confirmed_call_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        state.paused = False
        for index, call in enumerate(calls):
            permission = self.tools.permission_for(call.name)
            is_confirmed = call.id == confirmed_call_id
            if self.tools.requires_confirmation(call.name) and not is_confirmed:
                ticket = await self.confirmations.create(
                    state.run_id,
                    call,
                    permission or "trade",
                )
                confirmation_event = self._event(
                    state,
                    "confirmation_required",
                    step=step,
                    data={
                        "confirmation_id": ticket.id,
                        "tool_call_id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                        "permission": permission,
                        "expires_at": ticket.expires_at.isoformat(),
                    },
                )
                paused_event = self._event(
                    state,
                    "run_paused",
                    step=step,
                    data={"confirmation_id": ticket.id},
                )
                await self.checkpoints.save(
                    ticket.id,
                    RunCheckpoint(
                        run_id=state.run_id,
                        sequence=state.sequence,
                        step=step,
                        messages=state.messages,
                        pending_calls=calls[index:],
                    ),
                )
                state.paused = True
                yield confirmation_event
                yield paused_event
                return

            yield self._event(
                state,
                "tool_started",
                step=step,
                data={
                    "tool_call_id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                    "permission": permission,
                },
            )
            result = await self.tools.execute(
                call.name,
                call.arguments,
                confirmed=is_confirmed,
            )
            yield self._event(
                state,
                "tool_finished",
                step=step,
                data={
                    "tool_call_id": call.id,
                    "name": call.name,
                    **result.model_dump(mode="json"),
                },
            )
            state.messages.append(
                ModelMessage(
                    role="tool",
                    name=call.name,
                    tool_call_id=call.id,
                    content=self.context.serialize_tool_result(result),
                )
            )

    @staticmethod
    def _event(
        state: _RunState,
        event_type: str,
        *,
        step: int = 0,
        data: dict[str, object] | None = None,
    ) -> AgentEvent:
        state.sequence += 1
        return AgentEvent(
            type=event_type,  # type: ignore[arg-type]
            run_id=state.run_id,
            sequence=state.sequence,
            step=step,
            data=data or {},
        )
