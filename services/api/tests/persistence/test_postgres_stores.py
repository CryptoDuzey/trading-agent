import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.agent.models import AgentEvent, ToolCall
from app.agent.permissions import RunCheckpoint
from app.monitoring.models import AlertObservation, CreateAlertInput
from app.monitoring.rules import evaluate_alert
from app.monitoring.store import PostgresAlertStore
from app.persistence.database import Database
from app.persistence.stores import (
    PostgresCheckpointStore,
    PostgresConfirmationStore,
    PostgresConversationStore,
    PostgresRunTraceStore,
)
from app.portfolio.models import SavePositionInput
from app.portfolio.store import PostgresPositionStore

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


def test_alert_task_and_trigger_survive_new_store_instances() -> None:
    owner_id = f"test-owner-{uuid4()}"

    async def write_then_reopen():
        database = Database(DATABASE_URL or "")
        store = PostgresAlertStore(database)
        task = await store.create(
            owner_id,
            CreateAlertInput(
                market="spot",
                symbol="BTCUSDT",
                condition="price_below",
                threshold="65000",
                one_shot=True,
            ),
        )
        due = await store.list_due(datetime.now(UTC), limit=10)
        evaluation = evaluate_alert(
            task,
            AlertObservation(price=Decimal(64900)),
        )
        trigger = await store.record_evaluation(task.id, evaluation)
        await database.dispose()

        reopened = Database(DATABASE_URL or "")
        try:
            reopened_store = PostgresAlertStore(reopened)
            tasks = await reopened_store.list_for_owner(owner_id)
            triggers = await reopened_store.list_triggers(owner_id)
            return task, due, trigger, tasks, triggers
        finally:
            await reopened.dispose()

    task, due, trigger, tasks, triggers = asyncio.run(write_then_reopen())

    assert task.id in {item.id for item in due}
    assert trigger is not None
    assert tasks[0].status == "completed"
    assert tasks[0].trigger_count == 1
    assert triggers[0].reason == "BTCUSDT 价格 64900 已低于或等于 65000"
    assert triggers[0].notified is False


def test_conversation_summary_survives_restart_and_keeps_recent_turns() -> None:
    session_id = f"test-summary-{uuid4()}"

    async def write_then_reopen():
        database = Database(DATABASE_URL or "")
        store = PostgresConversationStore(database, max_messages=20)
        for index in range(1, 6):
            await store.append_exchange(session_id, f"问题 {index}", f"回答 {index}")
        batch = await store.get_compaction_batch(
            session_id,
            trigger_messages=8,
            keep_recent_messages=4,
        )
        assert batch is not None
        await store.save_compaction(session_id, batch, "前三轮对话的事实摘要")
        await database.dispose()

        reopened = Database(DATABASE_URL or "")
        try:
            return await PostgresConversationStore(reopened).get_recent(session_id)
        finally:
            await reopened.dispose()

    history = asyncio.run(write_then_reopen())

    assert history[0].role == "assistant"
    assert "前三轮对话的事实摘要" in history[0].content
    assert [message.content for message in history[1:]] == [
        "问题 4",
        "回答 4",
        "问题 5",
        "回答 5",
    ]


def test_position_survives_restart_and_upserts_without_duplicates() -> None:
    owner_id = f"test-position-{uuid4()}"

    async def write_then_reopen():
        database = Database(DATABASE_URL or "")
        store = PostgresPositionStore(database)
        first = await store.save(
            owner_id,
            SavePositionInput(
                market="usdm",
                symbol="BTCUSDT",
                side="long",
                quantity="0.1",
                entry_price="60000",
                leverage="2",
            ),
        )
        updated = await store.save(
            owner_id,
            SavePositionInput(
                market="usdm",
                symbol="BTCUSDT",
                side="long",
                quantity="0.2",
                entry_price="61000",
                leverage="3",
            ),
        )
        await database.dispose()

        reopened = Database(DATABASE_URL or "")
        try:
            positions = await PostgresPositionStore(reopened).list_for_owner(owner_id)
            return first, updated, positions
        finally:
            await reopened.dispose()

    first, updated, positions = asyncio.run(write_then_reopen())

    assert updated.id == first.id
    assert len(positions) == 1
    assert positions[0].quantity == Decimal("0.2")
