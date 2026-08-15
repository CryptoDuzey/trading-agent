import asyncio

from app.agent.tools import ToolRegistry
from app.monitoring.store import InMemoryAlertStore
from app.monitoring.tools import register_monitoring_tools


def test_monitoring_tools_create_list_pause_and_resume_owner_tasks() -> None:
    async def exercise_tools():
        store = InMemoryAlertStore()
        registry = ToolRegistry()
        register_monitoring_tools(registry, store, owner_id="owner-a")

        created = await registry.execute(
            "create_alert",
            {
                "market": "spot",
                "symbol": "BTCUSDT",
                "condition": "price_below",
                "threshold": "65000",
            },
        )
        task_id = created.output.id
        listed = await registry.execute("list_alerts", {})
        paused = await registry.execute("pause_alert", {"task_id": task_id})
        resumed = await registry.execute("resume_alert", {"task_id": task_id})
        return registry, created, listed, paused, resumed

    registry, created, listed, paused, resumed = asyncio.run(exercise_tools())

    assert {item["name"] for item in registry.definitions()} >= {
        "create_alert",
        "list_alerts",
        "pause_alert",
        "resume_alert",
    }
    assert created.ok is True
    assert listed.output.tasks[0].owner_id == "owner-a"
    assert paused.output.status == "paused"
    assert resumed.output.status == "active"


def test_monitoring_tool_owner_is_injected_not_chosen_by_model() -> None:
    registry = ToolRegistry()
    register_monitoring_tools(registry, InMemoryAlertStore(), owner_id="trusted-owner")

    create_definition = next(
        item for item in registry.definitions() if item["name"] == "create_alert"
    )

    assert "owner_id" not in create_definition["parameters"]["properties"]
