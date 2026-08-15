import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.models import AgentEvent

TraceStatus = Literal["running", "paused", "completed", "failed"]


class RunTrace(BaseModel):
    run_id: str
    session_id: str
    status: TraceStatus = "running"
    events: list[AgentEvent] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime | None = None


class InMemoryRunTraceStore:
    def __init__(self) -> None:
        self._traces: dict[str, RunTrace] = {}
        self._lock = asyncio.Lock()

    async def append(self, session_id: str, event: AgentEvent) -> None:
        async with self._lock:
            trace = self._traces.get(event.run_id)
            if trace is None:
                if event.sequence != 1:
                    raise ValueError(
                        f"Expected event sequence 1, received {event.sequence}"
                    )
                trace = RunTrace(
                    run_id=event.run_id,
                    session_id=session_id,
                    started_at=event.created_at,
                )
                self._traces[event.run_id] = trace
            elif trace.session_id != session_id:
                raise ValueError("A run trace cannot move between sessions")

            expected_sequence = len(trace.events) + 1
            if event.sequence != expected_sequence:
                raise ValueError(
                    f"Expected event sequence {expected_sequence}, "
                    f"received {event.sequence}"
                )
            if trace.status in {"completed", "failed"}:
                raise ValueError("Cannot append events to a finished run")
            if trace.status == "paused" and event.type != "run_resumed":
                raise ValueError("A paused run must resume before other events")

            trace.events.append(event.model_copy(deep=True))
            if event.type == "run_completed":
                trace.status = "completed"
                trace.finished_at = event.created_at
            elif event.type == "run_failed":
                trace.status = "failed"
                trace.finished_at = event.created_at
            elif event.type == "run_paused":
                trace.status = "paused"
            elif event.type == "run_resumed":
                trace.status = "running"

    async def get(self, run_id: str) -> RunTrace | None:
        async with self._lock:
            trace = self._traces.get(run_id)
            return trace.model_copy(deep=True) if trace else None

    async def replay(self, run_id: str) -> AsyncIterator[AgentEvent]:
        trace = await self.get(run_id)
        if trace is None:
            raise KeyError(f"Run trace not found: {run_id}")
        for event in trace.events:
            yield event.model_copy(deep=True)
