from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.tools.binance_market import Market

AlertCondition = Literal["price_above", "price_below"]
AlertStatus = Literal["active", "paused", "completed", "failed"]
NotificationChannel = Literal["site", "feishu"]


class CreateAlertInput(BaseModel):
    market: Market
    symbol: str = Field(min_length=2, max_length=40)
    condition: AlertCondition
    threshold: Decimal = Field(gt=0)
    check_interval_seconds: int = Field(default=60, ge=5, le=86_400)
    cooldown_seconds: int = Field(default=900, ge=0, le=604_800)
    one_shot: bool = True
    notification_channel: NotificationChannel = "site"

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class AlertTask(CreateAlertInput):
    id: str
    owner_id: str
    status: AlertStatus = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    next_check_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_checked_at: datetime | None = None
    last_triggered_at: datetime | None = None
    trigger_count: int = 0
    consecutive_errors: int = 0


class AlertObservation(BaseModel):
    price: Decimal = Field(gt=0)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AlertEvaluation(BaseModel):
    triggered: bool
    reason: str
    observation: AlertObservation


class AlertTrigger(BaseModel):
    id: str
    task_id: str
    reason: str
    observation: AlertObservation
    notified: bool = False
    notification_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
