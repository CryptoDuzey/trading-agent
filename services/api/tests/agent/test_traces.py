import asyncio

import pytest

from app.agent.models import AgentEvent
from app.agent.traces import InMemoryRunTraceStore


def make_event(event_type: str, sequence: int) -> AgentEvent:
    return AgentEvent(
        type=event_type,
        run_id="run-1",
        sequence=sequence,
        data={"sequence_value": sequence},
    )


def test_trace_store_preserves_order_and_final_status() -> None:
    store = InMemoryRunTraceStore()

    async def write_and_read():
        await store.append("session-1", make_event("run_started", 1))
        await store.append("session-1", make_event("model_started", 2))
        await store.append("session-1", make_event("run_completed", 3))
        return await store.get("run-1")

    trace = asyncio.run(write_and_read())

    assert trace is not None
    assert trace.session_id == "session-1"
    assert trace.status == "completed"
    assert [event.sequence for event in trace.events] == [1, 2, 3]


def test_trace_store_rejects_a_gap_in_event_sequence() -> None:
    store = InMemoryRunTraceStore()

    async def write_invalid_trace():
        await store.append("session-1", make_event("run_started", 1))
        await store.append("session-1", make_event("run_completed", 3))

    with pytest.raises(ValueError, match="Expected event sequence 2"):
        asyncio.run(write_invalid_trace())


def test_trace_replay_returns_independent_event_copies() -> None:
    store = InMemoryRunTraceStore()

    async def write_and_replay():
        await store.append("session-1", make_event("run_started", 1))
        replayed = [event async for event in store.replay("run-1")]
        replayed[0].data["sequence_value"] = 999
        original = await store.get("run-1")
        return replayed, original

    replayed, original = asyncio.run(write_and_replay())

    assert replayed[0].data["sequence_value"] == 999
    assert original is not None
    assert original.events[0].data["sequence_value"] == 1


def test_trace_status_moves_from_paused_back_to_running() -> None:
    store = InMemoryRunTraceStore()

    async def write_and_read_statuses():
        await store.append("session-1", make_event("run_started", 1))
        await store.append("session-1", make_event("run_paused", 2))
        paused = await store.get("run-1")
        await store.append("session-1", make_event("run_resumed", 3))
        running = await store.get("run-1")
        return paused, running

    paused, running = asyncio.run(write_and_read_statuses())

    assert paused is not None and paused.status == "paused"
    assert running is not None and running.status == "running"
