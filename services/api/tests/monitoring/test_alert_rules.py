import asyncio
from decimal import Decimal

import pytest

from app.monitoring.models import (
    AlertCondition,
    AlertObservation,
    CreateAlertInput,
)
from app.monitoring.rules import evaluate_alert
from app.monitoring.store import InMemoryAlertStore


def test_price_below_alert_triggers_at_the_configured_boundary() -> None:
    task = CreateAlertInput(
        market="spot",
        symbol="btcusdt",
        condition="price_below",
        threshold="65000",
    )

    quiet = evaluate_alert(
        task,
        AlertObservation(price=Decimal("65000.01")),
    )
    triggered = evaluate_alert(
        task,
        AlertObservation(price=Decimal(65000)),
    )

    assert task.symbol == "BTCUSDT"
    assert quiet.triggered is False
    assert triggered.triggered is True
    assert triggered.reason == "BTCUSDT 价格 65000 已低于或等于 65000"


@pytest.mark.parametrize(
    ("condition", "observed", "expected"),
    [
        ("price_above", "101", True),
        ("price_above", "99", False),
        ("price_below", "99", True),
        ("price_below", "101", False),
    ],
)
def test_price_conditions_are_deterministic(
    condition: AlertCondition,
    observed: str,
    expected: bool,
) -> None:
    task = CreateAlertInput(
        market="usdm",
        symbol="ETHUSDT",
        condition=condition,
        threshold="100",
    )

    result = evaluate_alert(task, AlertObservation(price=Decimal(observed)))

    assert result.triggered is expected


def test_alert_store_isolates_owners_and_controls_status() -> None:
    async def exercise_store():
        store = InMemoryAlertStore()
        first = await store.create(
            "owner-a",
            CreateAlertInput(
                market="spot",
                symbol="BTCUSDT",
                condition="price_below",
                threshold="65000",
            ),
        )
        await store.create(
            "owner-b",
            CreateAlertInput(
                market="spot",
                symbol="ETHUSDT",
                condition="price_above",
                threshold="4000",
            ),
        )
        paused = await store.set_status("owner-a", first.id, "paused")
        resumed = await store.set_status("owner-a", first.id, "active")
        return first, paused, resumed, await store.list_for_owner("owner-a")

    first, paused, resumed, tasks = asyncio.run(exercise_store())

    assert paused.status == "paused"
    assert resumed.status == "active"
    assert [task.id for task in tasks] == [first.id]


def test_alert_store_rejects_cross_owner_changes() -> None:
    async def exercise_store() -> None:
        store = InMemoryAlertStore()
        task = await store.create(
            "owner-a",
            CreateAlertInput(
                market="spot",
                symbol="BTCUSDT",
                condition="price_below",
                threshold="65000",
            ),
        )
        await store.set_status("owner-b", task.id, "paused")

    with pytest.raises(KeyError, match="Alert task not found"):
        asyncio.run(exercise_store())
