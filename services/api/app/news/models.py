from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

MacroImportance = Literal["low", "medium", "high"]


class MarketNewsInput(BaseModel):
    symbol: str | None = Field(default=None, max_length=40)
    topic: str | None = Field(default=None, max_length=200)


class NewsItem(BaseModel):
    title: str
    summary: str = ""
    source: str
    published_at: datetime
    url: str | None = None


class MarketNewsResult(BaseModel):
    symbol: str | None = None
    topic: str | None = None
    items: list[NewsItem]
    configured: bool
    source: str = "未配置"
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    limitation: str = "消息源未配置，无法获取真实新闻，因此不返回任何内容。"


class MacroEventsInput(BaseModel):
    lookahead_days: int = Field(default=7, ge=1, le=30)


class MacroEvent(BaseModel):
    title: str
    scheduled_at: datetime
    region: str = ""
    importance: MacroImportance = "medium"
    forecast: str | None = None
    previous: str | None = None


class MacroEventsResult(BaseModel):
    events: list[MacroEvent]
    configured: bool
    source: str = "未配置"
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    limitation: str = "宏观日历未配置，无法获取真实事件时间，因此不返回任何事件。"


class WebSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class WebSearchItem(BaseModel):
    title: str
    url: str
    snippet: str = ""


class WebSearchResult(BaseModel):
    query: str
    results: list[WebSearchItem]
    source: str = "DuckDuckGo"
    limitation: str = (
        "搜索结果来自公开网页搜索，可能不完整、有滞后或含观点性内容，"
        "需要结合其他工具交叉验证，不是投资建议。"
    )
