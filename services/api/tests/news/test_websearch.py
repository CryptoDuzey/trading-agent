import asyncio

from app.news.websearch import _clean_html, search_web

SAMPLE_HTML = """
<html><body>
<a rel="nofollow" href="https://example.com/news" class="result-link">美联储维持利率不变</a>
<td class="result-snippet">美联储在最新会议上维持利率不变，符合市场预期。</td>
<a rel="nofollow" href="https://example.org/btc" class="result-link">BTC 价格分析</a>
<td class="result-snippet">BTC 近期波动率上升，机构资金流入。</td>
</body></html>
"""


def test_clean_html_strips_tags_and_entities() -> None:
    assert _clean_html("<b>hello</b> &amp; world") == "hello & world"
    assert _clean_html("<a href='x'>标题</a>") == "标题"


def test_search_web_parses_links_and_snippets(monkeypatch) -> None:
    class FakeResponse:
        text = SAMPLE_HTML

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url, params=None):
            return FakeResponse()

    import app.news.websearch as ws

    monkeypatch.setattr(ws.httpx, "AsyncClient", FakeClient)

    results = asyncio.run(search_web("美联储 利率", limit=5))

    assert len(results) == 2
    assert results[0].title == "美联储维持利率不变"
    assert results[0].url == "https://example.com/news"
    assert "符合市场预期" in results[0].snippet
