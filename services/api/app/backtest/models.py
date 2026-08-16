from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.tools.binance_market import KlineInterval, Market

SignalKind = Literal["close_cross_above_ma", "close_cross_below_ma"]


class SignalBacktestInput(BaseModel):
    market: Market
    symbol: str = Field(min_length=2, max_length=40)
    interval: KlineInterval
    signal: SignalKind
    fast_window: int = Field(default=20, ge=2, le=200)
    forward_bars: int = Field(default=3, ge=1, le=30)
    limit: int = Field(default=500, ge=20, le=1000)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("limit")
    @classmethod
    def limit_must_cover_window(cls, value: int, info) -> int:
        fast = info.data.get("fast_window", 20)
        forward = info.data.get("forward_bars", 3)
        minimum = fast + forward + 1
        if value < minimum:
            raise ValueError(f"limit must be at least {minimum}")
        return value


class SignalBacktestResult(BaseModel):
    market: Market
    symbol: str
    interval: KlineInterval
    signal: SignalKind
    fast_window: int
    forward_bars: int
    total_samples: int
    win_rate_percent: float
    average_return_percent: float
    median_return_percent: float
    max_drawdown_percent: float
    source: Literal["Binance REST API"] = "Binance REST API"
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    limitation: str = (
        "回测只用历史 K 线收盘价与最低价，未计入手续费、滑点、资金费率；"
        "样本胜率只描述过去，不代表未来收益。"
    )
