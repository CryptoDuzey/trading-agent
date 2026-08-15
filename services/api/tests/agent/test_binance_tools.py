import asyncio

import httpx
import pytest

from app.agent.tools import ToolRegistry
from app.tools.binance_market import (
    BinanceMarketClient,
    BinanceMarketError,
    GetKlinesInput,
    GetQuoteInput,
    ScanMarketInput,
    TechnicalSnapshotInput,
    register_binance_market_tools,
)


def test_spot_quote_is_normalized_with_source_and_observation_time() -> None:
    async def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/ticker/price"
        assert request.url.params["symbol"] == "BTCUSDT"
        return httpx.Response(
            200,
            json={"symbol": "BTCUSDT", "price": "68420.12000000"},
        )

    async def get_quote():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        client = BinanceMarketClient(client=http_client)
        try:
            return await client.get_quote(
                GetQuoteInput(market="spot", symbol="btcusdt")
            )
        finally:
            await http_client.aclose()

    quote = asyncio.run(get_quote())

    assert quote.market == "spot"
    assert quote.symbol == "BTCUSDT"
    assert quote.price == "68420.12000000"
    assert quote.source == "Binance REST API"
    assert quote.observed_at.tzinfo is not None


def test_spot_klines_are_normalized_without_losing_price_precision() -> None:
    async def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/klines"
        assert request.url.params["interval"] == "15m"
        assert request.url.params["limit"] == "2"
        return httpx.Response(
            200,
            json=[
                [1000, "10.1", "11.2", "9.8", "10.9", "120.5", 1999],
                [2000, "10.9", "12.0", "10.7", "11.8", "180.2", 2999],
            ],
        )

    async def get_klines():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        client = BinanceMarketClient(client=http_client)
        try:
            return await client.get_klines(
                GetKlinesInput(
                    market="spot",
                    symbol="BTCUSDT",
                    interval="15m",
                    limit=2,
                )
            )
        finally:
            await http_client.aclose()

    result = asyncio.run(get_klines())

    assert result.candle_count == 2
    assert result.candles[0].open == "10.1"
    assert result.candles[-1].close == "11.8"
    assert result.source == "Binance REST API"


def test_binance_market_tools_are_exposed_to_the_agent() -> None:
    registry = ToolRegistry()
    register_binance_market_tools(registry, BinanceMarketClient())

    definitions = {item["name"]: item for item in registry.definitions()}

    assert set(definitions) == {
        "get_market_quote",
        "get_klines",
        "get_technical_snapshot",
        "scan_binance_market",
    }
    assert "market" in definitions["get_market_quote"]["parameters"]["properties"]


def test_binance_http_failure_is_explained_without_hiding_the_status() -> None:
    async def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(451, json={"msg": "Unavailable for legal reasons"})

    async def get_quote():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        client = BinanceMarketClient(client=http_client)
        try:
            return await client.get_quote(
                GetQuoteInput(market="usdm", symbol="BTCUSDT")
            )
        finally:
            await http_client.aclose()

    with pytest.raises(BinanceMarketError, match="HTTP 451"):
        asyncio.run(get_quote())


def test_market_scan_filters_quote_asset_and_ranks_liquid_large_moves() -> None:
    async def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/ticker/24hr"
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "AAAUSDT",
                    "lastPrice": "1.20",
                    "priceChangePercent": "20",
                    "quoteVolume": "5000000",
                    "highPrice": "1.25",
                    "lowPrice": "0.90",
                },
                {
                    "symbol": "BBBUSDT",
                    "lastPrice": "2.10",
                    "priceChangePercent": "8",
                    "quoteVolume": "9000000",
                    "highPrice": "2.20",
                    "lowPrice": "1.80",
                },
                {
                    "symbol": "AAAUSDC",
                    "lastPrice": "1.19",
                    "priceChangePercent": "30",
                    "quoteVolume": "12000000",
                    "highPrice": "1.30",
                    "lowPrice": "0.80",
                },
                {
                    "symbol": "TINYUSDT",
                    "lastPrice": "0.01",
                    "priceChangePercent": "80",
                    "quoteVolume": "1000",
                    "highPrice": "0.02",
                    "lowPrice": "0.005",
                },
            ],
        )

    async def scan_market():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        client = BinanceMarketClient(client=http_client)
        try:
            return await client.scan_market(
                ScanMarketInput(
                    market="spot",
                    quote_asset="USDT",
                    min_quote_volume=1_000_000,
                    limit=2,
                )
            )
        finally:
            await http_client.aclose()

    result = asyncio.run(scan_market())

    assert result.scanned_count == 4
    assert result.eligible_count == 2
    assert [item.symbol for item in result.opportunities] == ["AAAUSDT", "BBBUSDT"]
    assert result.opportunities[0].signals == ["24h大幅上涨"]
    assert "只代表市场异常排序" in result.limitation


def test_technical_snapshot_calculates_explainable_indicators() -> None:
    candles = [
        [
            index * 60_000,
            str(index),
            str(index + 1),
            str(index - 1),
            str(index),
            str(100 + index),
            index * 60_000 + 59_999,
        ]
        for index in range(1, 31)
    ]

    async def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/klines"
        return httpx.Response(200, json=candles)

    async def get_snapshot():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        client = BinanceMarketClient(client=http_client)
        try:
            return await client.get_technical_snapshot(
                TechnicalSnapshotInput(
                    market="spot",
                    symbol="BTCUSDT",
                    interval="15m",
                    limit=30,
                )
            )
        finally:
            await http_client.aclose()

    snapshot = asyncio.run(get_snapshot())

    assert snapshot.candle_count == 30
    assert snapshot.ma20 == 20.5
    assert snapshot.rsi14 == 100
    assert snapshot.atr14 == 2
    assert snapshot.volume_ratio20 > 1
    assert snapshot.trend == "上涨"
