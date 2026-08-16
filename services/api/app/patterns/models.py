from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.tools.binance_market import KlineInterval, Market

PatternName = Literal["support", "resistance", "double_top", "double_bottom"]


class DetectPatternsInput(BaseModel):
    market: Market
    symbol: str = Field(min_length=2, max_length=40)
    interval: KlineInterval
    limit: int = Field(default=120, ge=30, le=1000)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class Pattern(BaseModel):
    name: PatternName
    level: float
    description: str


class PatternResult(BaseModel):
    market: Market
    symbol: str
    interval: KlineInterval
    patterns: list[Pattern]
    latest_close: float
    source: Literal["Binance REST API"] = "Binance REST API"
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    limitation: str = (
        "形态识别只基于历史 K 线的高低点聚类，是描述性结论，"
        "不是买卖信号，也不保证未来走势。"
    )
