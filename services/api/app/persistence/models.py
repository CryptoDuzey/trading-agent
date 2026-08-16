from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
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
    summary: Mapped[str | None] = mapped_column(Text)
    summary_through_message_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
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


class AlertTaskRow(Base):
    __tablename__ = "alert_tasks"
    __table_args__ = (
        CheckConstraint(
            "market in ('spot', 'usdm', 'coinm', 'options')",
            name="alert_tasks_market_check",
        ),
        CheckConstraint(
            "condition in ('price_above', 'price_below')",
            name="alert_tasks_condition_check",
        ),
        CheckConstraint(
            "status in ('active', 'paused', 'completed', 'failed')",
            name="alert_tasks_status_check",
        ),
        CheckConstraint(
            "notification_channel in ('site', 'feishu')",
            name="alert_tasks_notification_channel_check",
        ),
        Index(
            "alert_tasks_owner_status_created_idx", "owner_id", "status", "created_at"
        ),
        Index(
            "alert_tasks_active_due_idx",
            "next_check_at",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    market: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    threshold: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    check_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    one_shot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notification_channel: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AlertCheckRow(Base):
    __tablename__ = "alert_checks"
    __table_args__ = (Index("alert_checks_task_created_idx", "task_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("alert_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    observed_price: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    triggered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AlertTriggerRow(Base):
    __tablename__ = "alert_triggers"
    __table_args__ = (
        Index("alert_triggers_task_created_idx", "task_id", "created_at"),
        Index(
            "alert_triggers_unnotified_idx",
            "created_at",
            postgresql_where=text("notified = false"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("alert_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    observed_price: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notification_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PositionRow(Base):
    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint(
            "market in ('spot', 'usdm', 'coinm', 'options')",
            name="positions_market_check",
        ),
        CheckConstraint(
            "side in ('long', 'short')",
            name="positions_side_check",
        ),
        CheckConstraint(
            "source in ('manual', 'binance')",
            name="positions_source_check",
        ),
        UniqueConstraint(
            "owner_id",
            "market",
            "symbol",
            "side",
            name="positions_owner_market_symbol_side_key",
        ),
        Index("positions_owner_opened_idx", "owner_id", "opened_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    market: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    entry_price: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    leverage: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    stop_loss: Mapped[Any] = mapped_column(Numeric(38, 18))
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
