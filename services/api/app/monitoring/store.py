import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.monitoring.models import (
    AlertEvaluation,
    AlertObservation,
    AlertStatus,
    AlertTask,
    AlertTrigger,
    CreateAlertInput,
)
from app.persistence.database import Database
from app.persistence.models import AlertCheckRow, AlertTaskRow, AlertTriggerRow


class InMemoryAlertStore:
    def __init__(self) -> None:
        self._tasks: dict[str, AlertTask] = {}
        self._triggers: dict[str, AlertTrigger] = {}
        self._lock = asyncio.Lock()

    async def create(self, owner_id: str, request: CreateAlertInput) -> AlertTask:
        now = datetime.now(UTC)
        task = AlertTask(
            id=str(uuid4()),
            owner_id=owner_id,
            **request.model_dump(),
            created_at=now,
            updated_at=now,
            next_check_at=now,
        )
        async with self._lock:
            self._tasks[task.id] = task
        return task.model_copy(deep=True)

    async def get(self, owner_id: str, task_id: str) -> AlertTask | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.owner_id != owner_id:
                return None
            return task.model_copy(deep=True)

    async def list_for_owner(self, owner_id: str) -> list[AlertTask]:
        async with self._lock:
            tasks = [
                task.model_copy(deep=True)
                for task in self._tasks.values()
                if task.owner_id == owner_id
            ]
        return sorted(tasks, key=lambda task: task.created_at)

    async def set_status(
        self,
        owner_id: str,
        task_id: str,
        status: AlertStatus,
    ) -> AlertTask:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.owner_id != owner_id:
                raise KeyError(f"Alert task not found: {task_id}")
            task.status = status
            task.updated_at = datetime.now(UTC)
            if status == "active":
                task.next_check_at = datetime.now(UTC)
            return task.model_copy(deep=True)

    async def list_due(self, now: datetime, *, limit: int = 100) -> list[AlertTask]:
        async with self._lock:
            tasks = [
                task.model_copy(deep=True)
                for task in self._tasks.values()
                if task.status == "active" and task.next_check_at <= now
            ]
        return sorted(tasks, key=lambda task: task.next_check_at)[:limit]

    async def record_evaluation(
        self,
        task_id: str,
        evaluation: AlertEvaluation,
    ) -> AlertTrigger | None:
        now = datetime.now(UTC)
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"Alert task not found: {task_id}")
            task.last_checked_at = evaluation.observation.observed_at
            task.consecutive_errors = 0
            task.updated_at = now
            if not evaluation.triggered:
                task.next_check_at = now + timedelta(
                    seconds=task.check_interval_seconds
                )
                return None

            trigger = AlertTrigger(
                id=str(uuid4()),
                task_id=task_id,
                reason=evaluation.reason,
                observation=evaluation.observation,
            )
            self._triggers[trigger.id] = trigger
            task.trigger_count += 1
            task.last_triggered_at = evaluation.observation.observed_at
            if task.one_shot:
                task.status = "completed"
            else:
                delay = max(task.check_interval_seconds, task.cooldown_seconds)
                task.next_check_at = now + timedelta(seconds=delay)
            return trigger.model_copy(deep=True)

    async def list_triggers(self, owner_id: str) -> list[AlertTrigger]:
        async with self._lock:
            task_ids = {
                task.id for task in self._tasks.values() if task.owner_id == owner_id
            }
            triggers = [
                trigger.model_copy(deep=True)
                for trigger in self._triggers.values()
                if trigger.task_id in task_ids
            ]
        return sorted(triggers, key=lambda trigger: trigger.created_at)

    async def mark_trigger_notification(
        self,
        trigger_id: str,
        *,
        notified: bool,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            trigger = self._triggers.get(trigger_id)
            if trigger is None:
                raise KeyError(f"Alert trigger not found: {trigger_id}")
            trigger.notified = notified
            trigger.notification_error = error

    async def record_error(self, task_id: str, message: str) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"Alert task not found: {task_id}")
            task.consecutive_errors += 1
            task.updated_at = datetime.now(UTC)
            task.next_check_at = datetime.now(UTC) + timedelta(
                seconds=task.check_interval_seconds
            )
            if task.consecutive_errors >= 5:
                task.status = "failed"


class PostgresAlertStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, owner_id: str, request: CreateAlertInput) -> AlertTask:
        now = datetime.now(UTC)
        row = AlertTaskRow(
            id=str(uuid4()),
            owner_id=owner_id,
            **request.model_dump(),
            status="active",
            next_check_at=now,
            trigger_count=0,
            consecutive_errors=0,
            created_at=now,
            updated_at=now,
        )
        async with self.database.sessions.begin() as session:
            session.add(row)
        return self._task(row)

    async def get(self, owner_id: str, task_id: str) -> AlertTask | None:
        async with self.database.sessions() as session:
            row = (
                await session.execute(
                    select(AlertTaskRow).where(
                        AlertTaskRow.id == task_id,
                        AlertTaskRow.owner_id == owner_id,
                    )
                )
            ).scalar_one_or_none()
            return self._task(row) if row else None

    async def list_for_owner(self, owner_id: str) -> list[AlertTask]:
        async with self.database.sessions() as session:
            rows = (
                await session.execute(
                    select(AlertTaskRow)
                    .where(AlertTaskRow.owner_id == owner_id)
                    .order_by(AlertTaskRow.created_at)
                )
            ).scalars()
            return [self._task(row) for row in rows]

    async def set_status(
        self,
        owner_id: str,
        task_id: str,
        status: AlertStatus,
    ) -> AlertTask:
        async with self.database.sessions.begin() as session:
            row = (
                await session.execute(
                    select(AlertTaskRow)
                    .where(
                        AlertTaskRow.id == task_id,
                        AlertTaskRow.owner_id == owner_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"Alert task not found: {task_id}")
            row.status = status
            row.updated_at = datetime.now(UTC)
            if status == "active":
                row.next_check_at = datetime.now(UTC)
            await session.flush()
            return self._task(row)

    async def list_due(self, now: datetime, *, limit: int = 100) -> list[AlertTask]:
        async with self.database.sessions() as session:
            rows = (
                await session.execute(
                    select(AlertTaskRow)
                    .where(
                        AlertTaskRow.status == "active",
                        AlertTaskRow.next_check_at <= now,
                    )
                    .order_by(AlertTaskRow.next_check_at)
                    .limit(limit)
                )
            ).scalars()
            return [self._task(row) for row in rows]

    async def record_evaluation(
        self,
        task_id: str,
        evaluation: AlertEvaluation,
    ) -> AlertTrigger | None:
        now = datetime.now(UTC)
        async with self.database.sessions.begin() as session:
            row = (
                await session.execute(
                    select(AlertTaskRow)
                    .where(AlertTaskRow.id == task_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"Alert task not found: {task_id}")

            session.add(
                AlertCheckRow(
                    task_id=task_id,
                    observed_price=evaluation.observation.price,
                    observed_at=evaluation.observation.observed_at,
                    triggered=evaluation.triggered,
                    reason=evaluation.reason,
                )
            )
            row.last_checked_at = evaluation.observation.observed_at
            row.consecutive_errors = 0
            row.updated_at = now
            trigger: AlertTrigger | None = None
            if evaluation.triggered:
                trigger = AlertTrigger(
                    id=str(uuid4()),
                    task_id=task_id,
                    reason=evaluation.reason,
                    observation=evaluation.observation,
                )
                session.add(
                    AlertTriggerRow(
                        id=trigger.id,
                        task_id=task_id,
                        reason=trigger.reason,
                        observed_price=trigger.observation.price,
                        observed_at=trigger.observation.observed_at,
                        notified=False,
                    )
                )
                row.trigger_count += 1
                row.last_triggered_at = evaluation.observation.observed_at
                if row.one_shot:
                    row.status = "completed"
                else:
                    delay = max(row.check_interval_seconds, row.cooldown_seconds)
                    row.next_check_at = now + timedelta(seconds=delay)
            else:
                row.next_check_at = now + timedelta(seconds=row.check_interval_seconds)
            return trigger

    async def list_triggers(self, owner_id: str) -> list[AlertTrigger]:
        async with self.database.sessions() as session:
            rows = (
                await session.execute(
                    select(AlertTriggerRow)
                    .join(AlertTaskRow, AlertTaskRow.id == AlertTriggerRow.task_id)
                    .where(AlertTaskRow.owner_id == owner_id)
                    .order_by(AlertTriggerRow.created_at)
                )
            ).scalars()
            return [self._trigger(row) for row in rows]

    async def mark_trigger_notification(
        self,
        trigger_id: str,
        *,
        notified: bool,
        error: str | None = None,
    ) -> None:
        async with self.database.sessions.begin() as session:
            row = await session.get(AlertTriggerRow, trigger_id, with_for_update=True)
            if row is None:
                raise KeyError(f"Alert trigger not found: {trigger_id}")
            row.notified = notified
            row.notification_error = error

    async def record_error(self, task_id: str, message: str) -> None:
        now = datetime.now(UTC)
        async with self.database.sessions.begin() as session:
            row = await session.get(AlertTaskRow, task_id, with_for_update=True)
            if row is None:
                raise KeyError(f"Alert task not found: {task_id}")
            row.consecutive_errors += 1
            row.updated_at = now
            row.next_check_at = now + timedelta(seconds=row.check_interval_seconds)
            if row.consecutive_errors >= 5:
                row.status = "failed"

    @staticmethod
    def _task(row: AlertTaskRow) -> AlertTask:
        return AlertTask(
            id=row.id,
            owner_id=row.owner_id,
            market=row.market,  # type: ignore[arg-type]
            symbol=row.symbol,
            condition=row.condition,  # type: ignore[arg-type]
            threshold=row.threshold,
            check_interval_seconds=row.check_interval_seconds,
            cooldown_seconds=row.cooldown_seconds,
            one_shot=row.one_shot,
            notification_channel=row.notification_channel,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            next_check_at=row.next_check_at,
            last_checked_at=row.last_checked_at,
            last_triggered_at=row.last_triggered_at,
            trigger_count=row.trigger_count,
            consecutive_errors=row.consecutive_errors,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _trigger(row: AlertTriggerRow) -> AlertTrigger:
        return AlertTrigger(
            id=row.id,
            task_id=row.task_id,
            reason=row.reason,
            observation=AlertObservation(
                price=row.observed_price,
                observed_at=row.observed_at,
            ),
            notified=row.notified,
            notification_error=row.notification_error,
            created_at=row.created_at,
        )
