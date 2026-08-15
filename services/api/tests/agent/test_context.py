import json
from datetime import UTC, datetime, timedelta

from app.agent.context import ContextManager, ContextPolicy
from app.agent.models import ModelMessage, ToolExecutionResult


def test_context_keeps_the_newest_complete_exchange_within_budget() -> None:
    manager = ContextManager(
        ContextPolicy(max_history_characters=28, max_history_messages=10)
    )
    history = [
        ModelMessage(role="user", content="old question 123"),
        ModelMessage(role="assistant", content="old answer 123"),
        ModelMessage(role="user", content="new question"),
        ModelMessage(role="assistant", content="new answer"),
    ]

    selected = manager.select_history(history)

    assert [message.content for message in selected] == [
        "new question",
        "new answer",
    ]


def test_context_marks_an_old_market_observation_as_stale() -> None:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    manager = ContextManager(
        ContextPolicy(market_data_max_age_seconds=60),
        now=lambda: now,
    )
    result = ToolExecutionResult(
        ok=True,
        output={
            "symbol": "BTCUSDT",
            "price": "63000.0",
            "observed_at": (now - timedelta(seconds=90)).isoformat(),
        },
    )

    payload = json.loads(manager.serialize_tool_result(result))

    assert payload["context_meta"]["is_stale"] is True
    assert payload["context_meta"]["age_seconds"] == 90


def test_context_truncates_a_large_tool_result_as_valid_json() -> None:
    manager = ContextManager(ContextPolicy(max_tool_result_characters=240))
    result = ToolExecutionResult(
        ok=True,
        output={"candles": ["x" * 100 for _ in range(20)]},
    )

    serialized = manager.serialize_tool_result(result)
    payload = json.loads(serialized)

    assert len(serialized) <= 240
    assert payload["context_meta"]["truncated"] is True
    assert payload["context_meta"]["original_characters"] > 2000
