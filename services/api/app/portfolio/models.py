from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.tools.binance_market import Market

PositionSide = Literal["long", "short"]
PositionSource = Literal["manual", "binance"]
RiskLevel = Literal["low", "medium", "high", "critical", "unknown"]


class SavePositionInput(BaseModel):
    market: Market
    symbol: str = Field(min_length=2, max_length=40)
    side: PositionSide
    quantity: Decimal = Field(gt=0)
    entry_price: Decimal = Field(gt=0)
    leverage: Decimal = Field(default=Decimal(1), ge=1, le=125)
    stop_loss: Decimal | None = Field(default=None, gt=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class Position(SavePositionInput):
    id: str
    owner_id: str
    source: PositionSource = "manual"
    opened_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PositionMark(BaseModel):
    price: Decimal = Field(gt=0)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PositionRisk(BaseModel):
    position_id: str
    market: Market
    symbol: str
    side: PositionSide
    quantity: Decimal
    mark_price: Decimal
    notional: float
    unrealized_pnl: float
    return_on_margin_percent: float
    stop_distance_percent: float | None = None


class RiskFlag(BaseModel):
    code: Literal[
        "missing_market_data",
        "stale_market_data",
        "missing_stop",
        "stop_crossed",
        "high_leverage",
        "concentration",
        "high_gross_leverage",
    ]
    level: Literal["medium", "high", "critical"]
    position_id: str | None = None
    message: str


class PortfolioRisk(BaseModel):
    positions: list[PositionRisk]
    total_notional: float
    total_unrealized_pnl: float
    gross_leverage: float | None
    largest_position_percent: float | None
    risk_level: RiskLevel
    flags: list[RiskFlag]
    observed_at: datetime
    limitation: str = (
        "风险基于当前价格和用户提供的持仓计算；未包含手续费、资金费率、"
        "滑点、强平阶梯和跨币种保证金变化。"
    )
