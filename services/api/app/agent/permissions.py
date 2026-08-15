import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from app.agent.models import ModelMessage, ToolCall, ToolPermission

ConfirmationStatus = Literal["pending", "approved", "denied", "consumed"]


class ConfirmationTicket(BaseModel):
    id: str
    run_id: str
    tool_call: ToolCall
    permission: ToolPermission
    status: ConfirmationStatus = "pending"
    created_at: datetime
    expires_at: datetime


class RunCheckpoint(BaseModel):
    run_id: str
    sequence: int
    step: int
    messages: list[ModelMessage]
    pending_calls: list[ToolCall]


class InMemoryConfirmationStore:
    def __init__(self, *, ttl_seconds: int = 600) -> None:
        self.ttl_seconds = ttl_seconds
        self._tickets: dict[str, ConfirmationTicket] = {}
        self._lock = asyncio.Lock()

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
        async with self._lock:
            self._tickets[ticket.id] = ticket
        return ticket.model_copy(deep=True)

    async def approve(self, confirmation_id: str) -> ConfirmationTicket:
        async with self._lock:
            ticket = self._require_active(confirmation_id)
            if ticket.status != "pending":
                raise ValueError("Confirmation is not pending")
            ticket.status = "approved"
            return ticket.model_copy(deep=True)

    async def consume(
        self,
        confirmation_id: str,
        *,
        run_id: str,
        tool_call: ToolCall,
    ) -> ConfirmationTicket:
        async with self._lock:
            ticket = self._require_active(confirmation_id)
            if ticket.status != "approved":
                raise ValueError("Confirmation has not been approved")
            if ticket.run_id != run_id or ticket.tool_call != tool_call:
                raise ValueError("Confirmation does not match the pending tool call")
            ticket.status = "consumed"
            return ticket.model_copy(deep=True)

    def _require_active(self, confirmation_id: str) -> ConfirmationTicket:
        ticket = self._tickets.get(confirmation_id)
        if ticket is None:
            raise ValueError("Confirmation was not found")
        if ticket.expires_at <= datetime.now(UTC):
            raise ValueError("Confirmation has expired")
        return ticket


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: dict[str, RunCheckpoint] = {}
        self._lock = asyncio.Lock()

    async def save(
        self,
        confirmation_id: str,
        checkpoint: RunCheckpoint,
    ) -> None:
        async with self._lock:
            self._checkpoints[confirmation_id] = checkpoint.model_copy(deep=True)

    async def get(self, confirmation_id: str) -> RunCheckpoint | None:
        async with self._lock:
            checkpoint = self._checkpoints.get(confirmation_id)
            return checkpoint.model_copy(deep=True) if checkpoint else None

    async def delete(self, confirmation_id: str) -> None:
        async with self._lock:
            self._checkpoints.pop(confirmation_id, None)
