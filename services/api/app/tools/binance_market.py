from datetime import UTC, datetime
from decimal import Decimal
from statistics import pstdev
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, field_validator

from app.agent.tools import ToolRegistry

Market = Literal["spot", "usdm", "coinm", "options"]
KlineInterval = Literal[
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
]

MARKET_ENDPOINTS: dict[str, tuple[str, str, str, str]] = {
    "spot": (
        "https://data-api.binance.vision",
        "/api/v3/ticker/price",
        "/api/v3/klines",
        "/api/v3/ticker/24hr",
    ),
    "usdm": (
        "https://fapi.binance.com",
        "/fapi/v1/ticker/price",
        "/fapi/v1/klines",
        "/fapi/v1/ticker/24hr",
    ),
    "coinm": (
        "https://dapi.binance.com",
        "/dapi/v1/ticker/price",
        "/dapi/v1/klines",
        "/dapi/v1/ticker/24hr",
    ),
    "options": (
        "https://eapi.binance.com",
        "/eapi/v1/ticker",
        "/eapi/v1/klines",
        "/eapi/v1/ticker",
    ),
}


class BinanceMarketError(RuntimeError):
    """A public Binance market request failed in a user-explainable way."""


class GetQuoteInput(BaseModel):
    market: Market = Field(description="Binance market family")
    symbol: str = Field(min_length=2, max_length=40)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class MarketQuote(BaseModel):
    market: Market
    symbol: str
    price: str
    source: Literal["Binance REST API"] = "Binance REST API"
    observed_at: datetime


class GetKlinesInput(GetQuoteInput):
    interval: KlineInterval
    limit: int = Field(default=100, ge=1, le=1000)


class Candle(BaseModel):
    open_time: int
    close_time: int
    open: str
    high: str
    low: str
    close: str
    volume: str


class KlineResult(BaseModel):
    market: Market
    symbol: str
    interval: KlineInterval
    candle_count: int
    candles: list[Candle]
    source: Literal["Binance REST API"] = "Binance REST API"
    observed_at: datetime


class ScanMarketInput(BaseModel):
    market: Market = Field(description="Binance market family")
    quote_asset: str = Field(default="USDT", max_length=12)
    min_quote_volume: float = Field(default=1_000_000, ge=0)
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("quote_asset")
    @classmethod
    def normalize_quote_asset(cls, value: str) -> str:
        return value.strip().upper()


class MarketOpportunity(BaseModel):
    symbol: str
    last_price: str
    price_change_percent_24h: float
    quote_volume_24h: float
    high_24h: str
    low_24h: str
    anomaly_score: float
    signals: list[str]


class MarketScanResult(BaseModel):
    market: Market
    quote_asset: str
    scanned_count: int
    eligible_count: int
    opportunities: list[MarketOpportunity]
    source: Literal["Binance REST API"] = "Binance REST API"
    observed_at: datetime
    limitation: str = "结果只代表市场异常排序，不代表上涨或下跌概率，也不是交易建议。"


class TechnicalSnapshotInput(GetKlinesInput):
    limit: int = Field(default=100, ge=21, le=1000)


class TechnicalSnapshot(BaseModel):
    market: Market
    symbol: str
    interval: KlineInterval
    candle_count: int
    latest_close: str
    ma20: float
    rsi14: float
    atr14: float
    bollinger_upper20: float
    bollinger_lower20: float
    volume_ratio20: float
    trend: Literal["上涨", "下跌", "震荡"]
    source: Literal["Binance REST API"] = "Binance REST API"
    observed_at: datetime
    limitation: str = "指标只描述已发生的价格和成交量，不预测未来收益。"


class BinanceMarketClient:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self._client = client
        self.timeout_seconds = timeout_seconds

    async def get_quote(self, request: GetQuoteInput) -> MarketQuote:
        base_url, quote_path, _, _ = MARKET_ENDPOINTS[request.market]
        payload = await self._get_json(
            f"{base_url}{quote_path}",
            params={"symbol": request.symbol},
        )
        if isinstance(payload, list):
            if not payload:
                raise ValueError(f"Binance returned no quote for {request.symbol}")
            payload = payload[0]
        if not isinstance(payload, dict):
            raise TypeError("Binance returned an invalid quote")

        price = payload.get("price") or payload.get("lastPrice")
        if price is None:
            raise ValueError("Binance quote did not contain a price")
        observed_at = self._observed_at(payload.get("time") or payload.get("closeTime"))
        return MarketQuote(
            market=request.market,
            symbol=str(payload.get("symbol") or request.symbol),
            price=str(price),
            observed_at=observed_at,
        )

    async def get_klines(self, request: GetKlinesInput) -> KlineResult:
        base_url, _, klines_path, _ = MARKET_ENDPOINTS[request.market]
        payload = await self._get_json(
            f"{base_url}{klines_path}",
            params={
                "symbol": request.symbol,
                "interval": request.interval,
                "limit": request.limit,
            },
        )
        if not isinstance(payload, list):
            raise TypeError("Binance returned invalid kline data")

        candles = [self._normalize_candle(item) for item in payload]
        return KlineResult(
            market=request.market,
            symbol=request.symbol,
            interval=request.interval,
            candle_count=len(candles),
            candles=candles,
            observed_at=datetime.now(UTC),
        )

    async def scan_market(self, request: ScanMarketInput) -> MarketScanResult:
        base_url, _, _, ticker_24h_path = MARKET_ENDPOINTS[request.market]
        payload = await self._get_json(f"{base_url}{ticker_24h_path}", params={})
        if not isinstance(payload, list):
            raise TypeError("Binance returned invalid 24-hour ticker data")

        eligible: list[MarketOpportunity] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", ""))
            if request.quote_asset and not symbol.endswith(request.quote_asset):
                continue
            try:
                change = float(item["priceChangePercent"])
                quote_volume = float(item.get("quoteVolume") or item.get("amount") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if quote_volume < request.min_quote_volume:
                continue

            signals: list[str] = []
            if change >= 10:
                signals.append("24h大幅上涨")
            elif change >= 5:
                signals.append("24h明显上涨")
            elif change <= -10:
                signals.append("24h大幅下跌")
            elif change <= -5:
                signals.append("24h明显下跌")
            eligible.append(
                MarketOpportunity(
                    symbol=symbol,
                    last_price=str(item.get("lastPrice") or item.get("last") or ""),
                    price_change_percent_24h=change,
                    quote_volume_24h=quote_volume,
                    high_24h=str(item.get("highPrice") or item.get("high") or ""),
                    low_24h=str(item.get("lowPrice") or item.get("low") or ""),
                    anomaly_score=round(abs(change), 4),
                    signals=signals,
                )
            )

        eligible.sort(
            key=lambda item: (
                item.anomaly_score,
                item.quote_volume_24h,
            ),
            reverse=True,
        )
        return MarketScanResult(
            market=request.market,
            quote_asset=request.quote_asset,
            scanned_count=len(payload),
            eligible_count=len(eligible),
            opportunities=eligible[: request.limit],
            observed_at=datetime.now(UTC),
        )

    async def get_technical_snapshot(
        self,
        request: TechnicalSnapshotInput,
    ) -> TechnicalSnapshot:
        result = await self.get_klines(
            GetKlinesInput(
                market=request.market,
                symbol=request.symbol,
                interval=request.interval,
                limit=request.limit,
            )
        )
        return self._technical_snapshot(result)

    @staticmethod
    def _technical_snapshot(result: KlineResult) -> TechnicalSnapshot:
        if len(result.candles) < 21:
            raise ValueError(
                "At least 21 candles are required for technical indicators"
            )

        closes = [Decimal(candle.close) for candle in result.candles]
        highs = [Decimal(candle.high) for candle in result.candles]
        lows = [Decimal(candle.low) for candle in result.candles]
        volumes = [Decimal(candle.volume) for candle in result.candles]

        ma20_decimal = sum(closes[-20:]) / Decimal(20)
        gains: list[Decimal] = []
        losses: list[Decimal] = []
        for previous, current in zip(closes[-15:-1], closes[-14:], strict=True):
            change = current - previous
            gains.append(max(change, Decimal(0)))
            losses.append(max(-change, Decimal(0)))
        average_gain = sum(gains) / Decimal(14)
        average_loss = sum(losses) / Decimal(14)
        if average_loss == 0:
            rsi14 = Decimal(100) if average_gain > 0 else Decimal(50)
        else:
            relative_strength = average_gain / average_loss
            rsi14 = Decimal(100) - Decimal(100) / (Decimal(1) + relative_strength)

        true_ranges: list[Decimal] = []
        for index in range(len(closes) - 14, len(closes)):
            previous_close = closes[index - 1]
            true_ranges.append(
                max(
                    highs[index] - lows[index],
                    abs(highs[index] - previous_close),
                    abs(lows[index] - previous_close),
                )
            )
        atr14 = sum(true_ranges) / Decimal(14)
        deviation = Decimal(str(pstdev(float(value) for value in closes[-20:])))
        upper = ma20_decimal + Decimal(2) * deviation
        lower = ma20_decimal - Decimal(2) * deviation
        previous_volume_average = sum(volumes[-21:-1]) / Decimal(20)
        volume_ratio = (
            volumes[-1] / previous_volume_average
            if previous_volume_average > 0
            else Decimal(0)
        )
        ma5 = sum(closes[-5:]) / Decimal(5)
        if closes[-1] > ma20_decimal and ma5 > ma20_decimal:
            trend: Literal["上涨", "下跌", "震荡"] = "上涨"
        elif closes[-1] < ma20_decimal and ma5 < ma20_decimal:
            trend = "下跌"
        else:
            trend = "震荡"

        def number(value: Decimal) -> float:
            return float(round(value, 8))

        return TechnicalSnapshot(
            market=result.market,
            symbol=result.symbol,
            interval=result.interval,
            candle_count=result.candle_count,
            latest_close=result.candles[-1].close,
            ma20=number(ma20_decimal),
            rsi14=number(rsi14),
            atr14=number(atr14),
            bollinger_upper20=number(upper),
            bollinger_lower20=number(lower),
            volume_ratio20=number(volume_ratio),
            trend=trend,
            observed_at=result.observed_at,
        )

    async def _get_json(
        self,
        url: str,
        *,
        params: dict[str, Any],
    ) -> Any:
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            response = await client.get(
                url,
                params=params,
                timeout=self.timeout_seconds,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                try:
                    detail = response.json().get("msg", response.text)
                except (ValueError, AttributeError):
                    detail = response.text
                raise BinanceMarketError(
                    f"Binance request failed with HTTP {response.status_code}: {detail}"
                ) from error
            return response.json()
        except httpx.RequestError as error:
            raise BinanceMarketError(
                f"Binance network request failed: {error}"
            ) from error
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _normalize_candle(item: Any) -> Candle:
        if not isinstance(item, list) or len(item) < 7:
            raise ValueError("Binance returned a malformed candle")
        return Candle(
            open_time=int(item[0]),
            open=str(item[1]),
            high=str(item[2]),
            low=str(item[3]),
            close=str(item[4]),
            volume=str(item[5]),
            close_time=int(item[6]),
        )

    @staticmethod
    def _observed_at(timestamp: Any) -> datetime:
        if timestamp is None:
            return datetime.now(UTC)
        return datetime.fromtimestamp(int(timestamp) / 1000, tz=UTC)


def register_binance_market_tools(
    registry: ToolRegistry,
    client: BinanceMarketClient,
) -> None:
    registry.register(
        name="get_market_quote",
        description=(
            "Get the current Binance price for a symbol from Spot, USD-M Futures, "
            "COIN-M Futures, or Options. Use this for any current-price claim."
        ),
        input_model=GetQuoteInput,
        handler=client.get_quote,
        timeout_seconds=12,
    )
    registry.register(
        name="scan_binance_market",
        description=(
            "Scan a Binance market and rank liquid symbols by absolute 24-hour "
            "price anomaly. This is opportunity discovery, not a forecast."
        ),
        input_model=ScanMarketInput,
        handler=client.scan_market,
        timeout_seconds=15,
    )
    registry.register(
        name="get_technical_snapshot",
        description=(
            "Calculate MA20, RSI14, ATR14, Bollinger Bands, volume ratio and "
            "a descriptive trend from Binance candlesticks."
        ),
        input_model=TechnicalSnapshotInput,
        handler=client.get_technical_snapshot,
        timeout_seconds=15,
    )
    registry.register(
        name="get_klines",
        description=(
            "Get recent Binance candlesticks with source time for technical analysis."
        ),
        input_model=GetKlinesInput,
        handler=client.get_klines,
        timeout_seconds=12,
    )
