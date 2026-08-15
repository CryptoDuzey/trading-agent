from datetime import UTC, datetime
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

MARKET_ENDPOINTS: dict[str, tuple[str, str, str]] = {
    "spot": (
        "https://data-api.binance.vision",
        "/api/v3/ticker/price",
        "/api/v3/klines",
    ),
    "usdm": (
        "https://fapi.binance.com",
        "/fapi/v1/ticker/price",
        "/fapi/v1/klines",
    ),
    "coinm": (
        "https://dapi.binance.com",
        "/dapi/v1/ticker/price",
        "/dapi/v1/klines",
    ),
    "options": (
        "https://eapi.binance.com",
        "/eapi/v1/ticker",
        "/eapi/v1/klines",
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
        base_url, quote_path, _ = MARKET_ENDPOINTS[request.market]
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
        base_url, _, klines_path = MARKET_ENDPOINTS[request.market]
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
        name="get_klines",
        description=(
            "Get recent Binance candlesticks with source time for technical analysis."
        ),
        input_model=GetKlinesInput,
        handler=client.get_klines,
        timeout_seconds=12,
    )
