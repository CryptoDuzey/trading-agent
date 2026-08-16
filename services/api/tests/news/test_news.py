import asyncio
from datetime import UTC, datetime

from app.agent.tools import ToolRegistry
from app.news.models import MacroEvent, NewsItem
from app.news.source import UnconfiguredNewsSource
from app.news.tools import register_news_tools


def test_unconfigured_news_source_reports_degradation() -> None:
    async def exercise():
        registry = ToolRegistry()
        register_news_tools(registry, UnconfiguredNewsSource())
        result = await registry.execute("get_market_news", {"topic": "BTC"})
        return result

    result = asyncio.run(exercise())

    assert result.ok is True
    assert result.output.items == []
    assert result.output.configured is False
    assert "未配置" in result.output.limitation


class FakeNewsSource:
    async def fetch_news(self, *, symbol, topic):
        return [
            NewsItem(
                title="美联储维持利率不变",
                summary="符合市场预期",
                source="测试源",
                published_at=datetime.now(UTC),
            )
        ]

    async def fetch_macro_events(self, *, lookahead_days):
        return [
            MacroEvent(
                title="美国 CPI",
                scheduled_at=datetime.now(UTC),
                region="美国",
                importance="high",
            )
        ]


def test_configured_news_source_returns_items() -> None:
    async def exercise():
        registry = ToolRegistry()
        register_news_tools(registry, FakeNewsSource())
        news = await registry.execute("get_market_news", {"topic": "BTC"})
        events = await registry.execute("get_macro_events", {"lookahead_days": 7})
        return news, events

    news, events = asyncio.run(exercise())

    assert news.output.configured is True
    assert len(news.output.items) == 1
    assert news.output.source == "测试源"
    assert events.output.configured is True
    assert len(events.output.events) == 1
    assert events.output.events[0].importance == "high"


def test_news_tools_are_read_only() -> None:
    registry = ToolRegistry()
    register_news_tools(registry, UnconfiguredNewsSource())
    assert registry.permission_for("get_market_news") == "read"
    assert registry.permission_for("get_macro_events") == "read"
