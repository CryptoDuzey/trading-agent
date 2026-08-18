from app.agent.tools import ToolRegistry
from app.news.models import (
    MacroEventsInput,
    MacroEventsResult,
    MarketNewsInput,
    MarketNewsResult,
    WebSearchInput,
    WebSearchItem,
    WebSearchResult,
)
from app.news.source import NewsSource
from app.news.websearch import search_web as _search_web


def register_news_tools(
    registry: ToolRegistry,
    source: NewsSource,
) -> None:
    async def get_news(request: MarketNewsInput) -> MarketNewsResult:
        items = await source.fetch_news(
            symbol=request.symbol,
            topic=request.topic,
        )
        return MarketNewsResult(
            symbol=request.symbol,
            topic=request.topic,
            items=items,
            configured=bool(items),
            source=items[0].source if items else "未配置",
            limitation=(
                "消息来自已配置的数据源，可能不完整或存在滞后。"
                if items
                else "消息源未配置，无法获取真实新闻，因此不返回任何内容。"
            ),
        )

    async def get_macro_events(request: MacroEventsInput) -> MacroEventsResult:
        events = await source.fetch_macro_events(
            lookahead_days=request.lookahead_days,
        )
        return MacroEventsResult(
            events=events,
            configured=bool(events),
            source="宏观日历" if events else "未配置",
            limitation=(
                "事件时间来自已配置的宏观日历，可能临时调整。"
                if events
                else "宏观日历未配置，无法获取真实事件时间，因此不返回任何事件。"
            ),
        )

    registry.register(
        name="get_market_news",
        description=(
            "Fetch sourced market news for a symbol or topic. Returns nothing "
            "instead of fabricating when no news source is configured."
        ),
        input_model=MarketNewsInput,
        handler=get_news,
        permission="read",
        timeout_seconds=15,
    )
    registry.register(
        name="get_macro_events",
        description=(
            "List upcoming macro events (CPI, FOMC, non-farm payrolls etc.) "
            "from the configured calendar. Returns nothing when not configured."
        ),
        input_model=MacroEventsInput,
        handler=get_macro_events,
        permission="read",
        timeout_seconds=15,
    )

    async def web_search(request: WebSearchInput) -> WebSearchResult:
        items = await _search_web(request.query, request.limit)
        return WebSearchResult(
            query=request.query,
            results=[
                WebSearchItem(title=item.title, url=item.url, snippet=item.snippet)
                for item in items
            ],
        )

    registry.register(
        name="search_web",
        description=(
            "Search the public web for news, articles and discussions related "
            "to a query. Use it to gather current information; results need "
            "cross-validation and are not investment advice."
        ),
        input_model=WebSearchInput,
        handler=web_search,
        permission="read",
        timeout_seconds=20,
    )
