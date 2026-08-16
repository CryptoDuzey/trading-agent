from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.tools.binance_market import Market

TradeSide = Literal["long", "short"]
PlanStatus = Literal["planned", "executed", "cancelled"]
OrderType = Literal["market", "limit"]
OrderStatus = Literal["filled", "cancelled"]


def _now() -> datetime:
    return datetime.now(UTC)


class CreateTradingPlanInput(BaseModel):
    market: Market
    symbol: str = Field(min_length=2, max_length=40)
    side: TradeSide
    entry_low: Decimal = Field(gt=0)
    entry_high: Decimal = Field(gt=0)
    stop_loss: Decimal = Field(gt=0)
    take_profit: Decimal = Field(gt=0)
    position_size: Decimal = Field(gt=0)
    risk_note: str = Field(min_length=1, max_length=2000)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("entry_high")
    @classmethod
    def entry_range_must_be_valid(
        cls,
        value: Decimal,
        info,
    ) -> Decimal:
        low = info.data.get("entry_low")
        if low is not None and value < low:
            raise ValueError("entry_high must not be below entry_low")
        return value


class TradingPlan(CreateTradingPlanInput):
    id: str
    owner_id: str
    status: PlanStatus = "planned"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class PlaceOrderInput(BaseModel):
    market: Market
    symbol: str = Field(min_length=2, max_length=40)
    side: TradeSide
    quantity: Decimal = Field(gt=0)
    order_type: OrderType = "market"
    limit_price: Decimal | None = Field(default=None, gt=0)
    plan_id: str | None = None
    reason: str = Field(default="", max_length=2000)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("limit_price")
    @classmethod
    def limit_order_needs_price(
        cls,
        value: Decimal | None,
        info,
    ) -> Decimal | None:
        if info.data.get("order_type") == "limit" and value is None:
            raise ValueError("limit_price is required for limit orders")
        return value


class SimulatedOrder(BaseModel):
    id: str
    owner_id: str
    market: Market
    symbol: str
    side: TradeSide
    quantity: Decimal
    order_type: OrderType
    limit_price: Decimal | None = None
    plan_id: str | None = None
    reason: str = ""
    status: OrderStatus
    filled_price: Decimal | None = None
    filled_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)


class CreateTradeReviewInput(BaseModel):
    market: Market
    symbol: str = Field(min_length=2, max_length=40)
    side: TradeSide
    entry_price: Decimal = Field(gt=0)
    exit_price: Decimal | None = Field(default=None, gt=0)
    quantity: Decimal = Field(gt=0)
    entry_reason: str = Field(min_length=1, max_length=2000)
    outcome_notes: str = Field(default="", max_length=2000)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class TradeReview(CreateTradeReviewInput):
    id: str
    owner_id: str
    realized_pnl: Decimal | None = None
    created_at: datetime = Field(default_factory=_now)
