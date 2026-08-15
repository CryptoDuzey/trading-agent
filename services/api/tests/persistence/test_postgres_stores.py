import asyncio
import os
from uuid import uuid4

import pytest

from app.agent.models import AgentEvent, ToolCall
from app.agent.permissions import RunCheckpoint
from app.persistence.database import Database
from app.persistence.stores import (
    PostgresCheckpointStore,
    PostgresConfirmationStore,
    PostgresConversationStore,
    PostgresRunTraceStore,
)

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


def test_conversation_and_trace_survive_new_store_instances() -> None:
    session_id = f"test-session-{uuid4()}"
    run_id = str(uuid4())

    async def write_then_reopen():
        database = Database(DATABASE_URL or "")
        conversations = PostgresConversationStore(database, max_messages=20)
        traces = PostgresRunTraceStore(database)
        await conversations.append_exchange(session_id, "BTC?", "63000")
        await traces.append(
            session_id,
            AgentEvent(type="run_started", run_id=run_id, sequence=1),
        )
        await traces.append(
            session_id,
            AgentEvent(type="run_completed", run_id=run_id, sequence=2),
        )
        await database.dispose()

        reopened = Database(DATABASE_URL or "")
        try:
            history = await PostgresConversationStore(reopened).get_recent(session_id)
            trace = await PostgresRunTraceStore(reopened).get(run_id)
            return history, trace
        finally:
            await reopened.dispose()

    history, trace = asyncio.run(write_then_reopen())

    assert [message.content for message in history] == ["BTC?", "63000"]
    assert trace is not None
    assert trace.session_id == session_id
    assert trace.status == "completed"
    assert [event.sequence for event in trace.events] == [1, 2]


def test_confirmation_and_checkpoint_survive_new_store_instances() -> None:
    session_id = f"test-confirm-{uuid4()}"
    run_id = str(uuid4())
    tool_call = ToolCall(
        id="tool-call-1",
        name="simulate_order",
        arguments={"symbol": "BTCUSDT", "quantity": "0.01"},
    )

    async def write_then_resume():
        database = Database(DATABASE_URL or "")
        traces = PostgresRunTraceStore(database)
        confirmations = PostgresConfirmationStore(database)
        checkpoints = PostgresCheckpointStore(database)
        await traces.append(
            session_id,
            AgentEvent(type="run_started", run_id=run_id, sequence=1),
        )
        ticket = await confirmations.create(run_id, tool_call, "simulate")
        await checkpoints.save(
            ticket.id,
            RunCheckpoint(
                run_id=run_id,
                sequence=1,
                step=1,
                messages=[],
                pending_calls=[tool_call],
            ),
        )
        await database.dispose()

        reopened = Database(DATABASE_URL or "")
        try:
            reopened_confirmations = PostgresConfirmationStore(reopened)
            reopened_checkpoints = PostgresCheckpointStore(reopened)
            checkpoint = await reopened_checkpoints.get(ticket.id)
            await reopened_confirmations.approve(ticket.id)
            consumed = await reopened_confirmations.consume(
                ticket.id,
                run_id=run_id,
                tool_call=tool_call,
            )
            return checkpoint, consumed
        finally:
            await reopened.dispose()

    checkpoint, ticket = asyncio.run(write_then_resume())

    assert checkpoint is not None
    assert checkpoint.pending_calls == [tool_call]
    assert ticket.status == "consumed"
