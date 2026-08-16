from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.tools.binance_market import KlineInterval, Market


class EventBacktestInput(BaseModel):
    market: Market
    symbol: str = Field(min_length=2, max_length=40)
    interval: KlineInterval
    event_time: datetime
    lookback_bars: int = Field(default=12, ge=1, le=500)
    forward_bars: int = Field(default=6, ge=1, le=120)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("event_time")
    @classmethod
    def ensure_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class EventBacktestResult(BaseModel):
    market: Market
    symbol: str
    interval: KlineInterval
    event_time: datetime
    baseline_close: float
    forward_closes: list[float]
    change_percent: float
    max_up_percent: float
    max_down_percent: float
    source: Literal["Binance REST API"] = "Binance REST API"
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    limitation: str = (
        "事件影响只用该次事件前后的历史 K 线描述，样本量为 1，"
        "不是统计胜率，也不构成对未来同类事件的预测。"
    )
