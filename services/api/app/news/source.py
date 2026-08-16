from typing import Protocol

from app.news.models import MacroEvent, NewsItem


class NewsSource(Protocol):
    """Pluggable provider for news and macro events (Jin10, X, etc.).

    Implementations must return only real, sourced items. Returning an empty
    list is the correct behaviour when the provider is not configured, so the
    tool layer can report that instead of fabricating news.
    """

    async def fetch_news(
        self,
        *,
        symbol: str | None,
        topic: str | None,
    ) -> list[NewsItem]: ...

    async def fetch_macro_events(self, *, lookahead_days: int) -> list[MacroEvent]: ...


class UnconfiguredNewsSource:
    """Fallback used before a real news/macro provider is configured."""

    async def fetch_news(
        self,
        *,
        symbol: str | None,
        topic: str | None,
    ) -> list[NewsItem]:
        return []

    async def fetch_macro_events(self, *, lookahead_days: int) -> list[MacroEvent]:
        return []
