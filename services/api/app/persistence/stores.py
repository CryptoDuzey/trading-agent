from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.agent.memory import SUMMARY_PREFIX
from app.agent.models import (
    AgentEvent,
    ConversationCompactionBatch,
    ModelMessage,
    ToolCall,
    ToolPermission,
)
from app.agent.permissions import ConfirmationTicket, RunCheckpoint
from app.agent.traces import RunTrace
from app.persistence.database import Database
from app.persistence.models import (
    AgentCheckpointRow,
    AgentEventRow,
    AgentRunRow,
    ConfirmationTicketRow,
    ConversationRow,
    MessageRow,
)


class PostgresConversationStore:
    def __init__(self, database: Database, *, max_messages: int = 20) -> None:
        self.database = database
        self.max_messages = max_messages

    async def append_exchange(
        self,
        session_id: str,
        user_content: str,
        assistant_content: str,
    ) -> None:
        async with self.database.sessions.begin() as session:
            await session.execute(
                insert(ConversationRow)
                .values(id=session_id)
                .on_conflict_do_update(
                    index_elements=[ConversationRow.id],
                    set_={"updated_at": func.now()},
                )
            )
            session.add_all(
                [
                    MessageRow(
                        session_id=session_id,
                        role="user",
                        content=user_content,
                    ),
                    MessageRow(
                        session_id=session_id,
                        role="assistant",
                        content=assistant_content,
                    ),
                ]
            )

    async def get_recent(self, session_id: str) -> list[ModelMessage]:
        async with self.database.sessions() as session:
            conversation = await session.get(ConversationRow, session_id)
            if conversation is None:
                return []
            rows = (
                await session.execute(
                    select(MessageRow)
                    .where(
                        MessageRow.session_id == session_id,
                        MessageRow.id > conversation.summary_through_message_id,
                    )
                    .order_by(MessageRow.id.desc())
                    .limit(self.max_messages)
                )
            ).scalars()
            messages = [
                ModelMessage(role=row.role, content=row.content)  # type: ignore[arg-type]
                for row in rows
            ]
            messages.reverse()
            if conversation.summary:
                messages.insert(
                    0,
                    ModelMessage(
                        role="assistant",
                        content=SUMMARY_PREFIX + conversation.summary,
                    ),
                )
            return messages

    async def get_compaction_batch(
        self,
        session_id: str,
        *,
        trigger_messages: int,
        keep_recent_messages: int,
    ) -> ConversationCompactionBatch | None:
        async with self.database.sessions() as session:
            conversation = await session.get(ConversationRow, session_id)
            if conversation is None:
                return None
            rows = list(
                (
                    await session.execute(
                        select(MessageRow)
                        .where(
                            MessageRow.session_id == session_id,
                            MessageRow.id
                            > conversation.summary_through_message_id,
                        )
                        .order_by(MessageRow.id)
                    )
                ).scalars()
            )
            if len(rows) < trigger_messages:
                return None
            compacted_rows = rows[: len(rows) - keep_recent_messages]
            if not compacted_rows:
                return None
            return ConversationCompactionBatch(
                previous_summary=conversation.summary,
                previous_through_message_id=conversation.summary_through_message_id,
                through_message_id=compacted_rows[-1].id,
                messages=[
                    ModelMessage(
                        role=row.role,  # type: ignore[arg-type]
                        content=row.content,
                    )
                    for row in compacted_rows
                ],
            )

    async def save_compaction(
        self,
        session_id: str,
        batch: ConversationCompactionBatch,
        summary: str,
    ) -> None:
        if batch.through_message_id is None:
            raise ValueError("PostgreSQL compaction requires a message cursor")
        async with self.database.sessions.begin() as session:
            conversation = (
                await session.execute(
                    select(ConversationRow)
                    .where(ConversationRow.id == session_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if conversation is None:
                raise KeyError(f"Conversation not found: {session_id}")
            if (
                conversation.summary_through_message_id
                != (batch.previous_through_message_id or 0)
            ):
                raise RuntimeError("Conversation was compacted concurrently")
            conversation.summary = summary
            conversation.summary_through_message_id = batch.through_message_id
            conversation.updated_at = datetime.now(UTC)


class PostgresRunTraceStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def append(self, session_id: str, event: AgentEvent) -> None:
        async with self.database.sessions.begin() as session:
            await session.execute(
                insert(ConversationRow)
                .values(id=session_id)
                .on_conflict_do_nothing(index_elements=[ConversationRow.id])
            )
            run = (
                await session.execute(
                    select(AgentRunRow)
                    .where(AgentRunRow.run_id == event.run_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()

            if run is None:
                if event.sequence != 1:
                    raise ValueError(
                        f"Expected event sequence 1, received {event.sequence}"
                    )
                run = AgentRunRow(
                    run_id=event.run_id,
                    session_id=session_id,
                    status="running",
                    last_sequence=0,
                    started_at=event.created_at,
                )
                session.add(run)
                # The models deliberately avoid ORM relationships. Flush the
                # parent row before adding its first event so PostgreSQL can
                # enforce the foreign key deterministically.
                await session.flush()
            else:
                if run.session_id != session_id:
                    raise ValueError("A run trace cannot move between sessions")
                if run.status in {"completed", "failed"}:
                    raise ValueError("Cannot append events to a finished run")
                if run.status == "paused" and event.type != "run_resumed":
                    raise ValueError("A paused run must resume before other events")

            expected_sequence = run.last_sequence + 1
            if event.sequence != expected_sequence:
                raise ValueError(
                    f"Expected event sequence {expected_sequence}, "
                    f"received {event.sequence}"
                )

            session.add(
                AgentEventRow(
                    run_id=event.run_id,
                    sequence=event.sequence,
                    type=event.type,
                    step=event.step,
                    data=event.data,
                    created_at=event.created_at,
                )
            )
            run.last_sequence = event.sequence
            if event.type == "run_completed":
                run.status = "completed"
                run.finished_at = event.created_at
            elif event.type == "run_failed":
                run.status = "failed"
                run.finished_at = event.created_at
            elif event.type == "run_paused":
                run.status = "paused"
            elif event.type == "run_resumed":
                run.status = "running"

    async def get(self, run_id: str) -> RunTrace | None:
        async with self.database.sessions() as session:
            run = await session.get(AgentRunRow, run_id)
            if run is None:
                return None
            event_rows = (
                await session.execute(
                    select(AgentEventRow)
                    .where(AgentEventRow.run_id == run_id)
                    .order_by(AgentEventRow.sequence)
                )
            ).scalars()
            events = [
                AgentEvent(
                    type=row.type,  # type: ignore[arg-type]
                    run_id=row.run_id,
                    sequence=row.sequence,
                    step=row.step,
                    data=row.data,
                    created_at=row.created_at,
                )
                for row in event_rows
            ]
            return RunTrace(
                run_id=run.run_id,
                session_id=run.session_id,
                status=run.status,  # type: ignore[arg-type]
                events=events,
                started_at=run.started_at,
                finished_at=run.finished_at,
            )

    async def replay(self, run_id: str):
        trace = await self.get(run_id)
        if trace is None:
            raise KeyError(f"Run trace not found: {run_id}")
        for event in trace.events:
            yield event.model_copy(deep=True)


class PostgresConfirmationStore:
    def __init__(self, database: Database, *, ttl_seconds: int = 600) -> None:
        self.database = database
        self.ttl_seconds = ttl_seconds

    async def create(
        self,
        run_id: str,
        tool_call: ToolCall,
        permission: ToolPermission,
    ) -> ConfirmationTicket:
        now = datetime.now(UTC)
        ticket = ConfirmationTicket(
            id=str(uuid4()),
            run_id=run_id,
            tool_call=tool_call.model_copy(deep=True),
            permission=permission,
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        async with self.database.sessions.begin() as session:
            session.add(
                ConfirmationTicketRow(
                    id=ticket.id,
                    run_id=ticket.run_id,
                    tool_call=ticket.tool_call.model_dump(mode="json"),
                    permission=ticket.permission,
                    status=ticket.status,
                    created_at=ticket.created_at,
                    expires_at=ticket.expires_at,
                )
            )
        return ticket

    async def approve(self, confirmation_id: str) -> ConfirmationTicket:
        async with self.database.sessions.begin() as session:
            row = await self._get_active_row(session, confirmation_id)
            if row.status != "pending":
                raise ValueError("Confirmation is not pending")
            row.status = "approved"
            return self._ticket(row)

    async def consume(
        self,
        confirmation_id: str,
        *,
        run_id: str,
        tool_call: ToolCall,
    ) -> ConfirmationTicket:
        async with self.database.sessions.begin() as session:
            row = await self._get_active_row(session, confirmation_id)
            if row.status != "approved":
                raise ValueError("Confirmation has not been approved")
            if (
                row.run_id != run_id
                or ToolCall.model_validate(row.tool_call) != tool_call
            ):
                raise ValueError("Confirmation does not match the pending tool call")
            row.status = "consumed"
            return self._ticket(row)

    async def _get_active_row(self, session, confirmation_id: str):
        row = (
            await session.execute(
                select(ConfirmationTicketRow)
                .where(ConfirmationTicketRow.id == confirmation_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ValueError("Confirmation was not found")
        if row.expires_at <= datetime.now(UTC):
            raise ValueError("Confirmation has expired")
        return row

    @staticmethod
    def _ticket(row: ConfirmationTicketRow) -> ConfirmationTicket:
        return ConfirmationTicket(
            id=row.id,
            run_id=row.run_id,
            tool_call=ToolCall.model_validate(row.tool_call),
            permission=row.permission,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            created_at=row.created_at,
            expires_at=row.expires_at,
        )


class PostgresCheckpointStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(
        self,
        confirmation_id: str,
        checkpoint: RunCheckpoint,
    ) -> None:
        values = {
            "confirmation_id": confirmation_id,
            "run_id": checkpoint.run_id,
            "sequence": checkpoint.sequence,
            "step": checkpoint.step,
            "messages": [
                message.model_dump(mode="json") for message in checkpoint.messages
            ],
            "pending_calls": [
                call.model_dump(mode="json") for call in checkpoint.pending_calls
            ],
        }
        async with self.database.sessions.begin() as session:
            await session.execute(
                insert(AgentCheckpointRow)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[AgentCheckpointRow.confirmation_id],
                    set_={**values, "updated_at": func.now()},
                )
            )

    async def get(self, confirmation_id: str) -> RunCheckpoint | None:
        async with self.database.sessions() as session:
            row = await session.get(AgentCheckpointRow, confirmation_id)
            if row is None:
                return None
            return RunCheckpoint(
                run_id=row.run_id,
                sequence=row.sequence,
                step=row.step,
                messages=[ModelMessage.model_validate(item) for item in row.messages],
                pending_calls=[
                    ToolCall.model_validate(item) for item in row.pending_calls
                ],
            )

    async def delete(self, confirmation_id: str) -> None:
        async with self.database.sessions.begin() as session:
            row = await session.get(AgentCheckpointRow, confirmation_id)
            if row is not None:
                await session.delete(row)
