import re
from dataclasses import dataclass

import httpx

_LINK_RE = re.compile(
    r'<a[^>]+href="([^"]+)"[^>]+class="result-link"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'<td[^>]+class="result-snippet"[^>]*>(.*?)</td>',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class WebSearchItem:
    title: str
    url: str
    snippet: str


def _clean_html(raw: str) -> str:
    text = _TAG_RE.sub("", raw)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#x27;", "'")
    return " ".join(text.split())


async def search_web(query: str, limit: int = 5) -> list[WebSearchItem]:
    """Search the web via DuckDuckGo's lite interface (no API key required)."""
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0 (compatible; TradingAgent/0.1)"},
    ) as client:
        response = await client.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query},
        )
        response.raise_for_status()
        html = response.text

    links = _LINK_RE.findall(html)
    snippets = _SNIPPET_RE.findall(html)

    results: list[WebSearchItem] = []
    for index, (url, raw_title) in enumerate(links[:limit]):
        title = _clean_html(raw_title)
        snippet = _clean_html(snippets[index]) if index < len(snippets) else ""
        if not title or not url:
            continue
        results.append(WebSearchItem(title=title, url=url, snippet=snippet))
    return results
