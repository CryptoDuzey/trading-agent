from pydantic import BaseModel, Field

from app.agent.tools import ToolRegistry
from app.monitoring.models import AlertTask, CreateAlertInput
from app.monitoring.store import InMemoryAlertStore, PostgresAlertStore

AlertStore = InMemoryAlertStore | PostgresAlertStore


class ListAlertsInput(BaseModel):
    pass


class ListAlertsOutput(BaseModel):
    tasks: list[AlertTask]


class ManageAlertInput(BaseModel):
    task_id: str = Field(min_length=36, max_length=36)


def register_monitoring_tools(
    registry: ToolRegistry,
    store: AlertStore,
    *,
    owner_id: str,
) -> None:
    async def create_alert(request: CreateAlertInput) -> AlertTask:
        return await store.create(owner_id, request)

    async def list_alerts(_: ListAlertsInput) -> ListAlertsOutput:
        return ListAlertsOutput(tasks=await store.list_for_owner(owner_id))

    async def pause_alert(request: ManageAlertInput) -> AlertTask:
        return await store.set_status(owner_id, request.task_id, "paused")

    async def resume_alert(request: ManageAlertInput) -> AlertTask:
        return await store.set_status(owner_id, request.task_id, "active")

    registry.register(
        name="create_alert",
        description=(
            "Create a persistent Binance price monitor requested by the user. "
            "Ask for any missing market, symbol, direction or threshold first."
        ),
        input_model=CreateAlertInput,
        handler=create_alert,
        permission="write",
    )
    registry.register(
        name="list_alerts",
        description="List the current user's persistent monitoring tasks.",
        input_model=ListAlertsInput,
        handler=list_alerts,
        permission="read",
    )
    registry.register(
        name="pause_alert",
        description="Pause one of the current user's monitoring tasks.",
        input_model=ManageAlertInput,
        handler=pause_alert,
        permission="write",
    )
    registry.register(
        name="resume_alert",
        description="Resume one of the current user's paused monitoring tasks.",
        input_model=ManageAlertInput,
        handler=resume_alert,
        permission="write",
    )
