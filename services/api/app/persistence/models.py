from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MessageRow(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role in ('system', 'user', 'assistant', 'tool')",
            name="messages_role_check",
        ),
        Index("messages_session_id_id_idx", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status in ('running', 'paused', 'completed', 'failed')",
            name="agent_runs_status_check",
        ),
        Index(
            "agent_runs_session_status_started_idx",
            "session_id",
            "status",
            "started_at",
        ),
    )

    run_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentEventRow(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="agent_events_run_sequence_key"),
        Index("agent_events_run_id_sequence_idx", "run_id", "sequence"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ConfirmationTicketRow(Base):
    __tablename__ = "confirmation_tickets"
    __table_args__ = (
        CheckConstraint(
            "permission in ('simulate', 'trade')",
            name="confirmation_tickets_permission_check",
        ),
        CheckConstraint(
            "status in ('pending', 'approved', 'denied', 'consumed')",
            name="confirmation_tickets_status_check",
        ),
        Index(
            "confirmation_tickets_pending_expires_idx",
            "expires_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("confirmation_tickets_run_id_idx", "run_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_call: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    permission: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AgentCheckpointRow(Base):
    __tablename__ = "agent_checkpoints"
    __table_args__ = (Index("agent_checkpoints_run_id_idx", "run_id"),)

    confirmation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("confirmation_tickets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    pending_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
