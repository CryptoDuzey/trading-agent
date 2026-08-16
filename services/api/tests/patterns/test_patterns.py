import asyncio
from datetime import UTC, datetime

from app.agent.tools import ToolRegistry
from app.patterns.engine import detect_patterns
from app.patterns.tools import register_pattern_tools
from app.tools.binance_market import Candle, KlineResult


def _candles(highs, lows):
    return [
        Candle(
            open_time=i,
            close_time=i,
            open=str((h + l) / 2),
            high=str(h),
            low=str(l),
            close=str((h + l) / 2),
            volume="1",
        )
        for i, (h, l) in enumerate(zip(highs, lows, strict=True))
    ]


def _oscillating() -> list[Candle]:
    highs = [105, 108, 110, 110, 108, 105, 102, 100, 100, 102, 105, 108, 110, 110, 108, 105, 102, 100, 100, 102, 105]
    lows = [100, 102, 105, 107, 105, 102, 100, 98, 98, 100, 102, 105, 107, 105, 102, 100, 98, 98, 98, 100, 102]
    return _candles(highs, lows)


def test_detect_reports_support_and_resistance() -> None:
    patterns = detect_patterns(_oscillating(), pivot_window=3, tolerance=0.02)
    names = {pattern.name for pattern in patterns}
    assert "support" in names
    assert "resistance" in names


def test_detect_finds_double_top_and_bottom() -> None:
    patterns = detect_patterns(_oscillating(), pivot_window=3, tolerance=0.02)
    names = {pattern.name for pattern in patterns}
    assert "double_top" in names
    assert "double_bottom" in names


def test_insufficient_candles_raises() -> None:
    try:
        detect_patterns(_candles([100] * 5, [99] * 5), pivot_window=3)
    except ValueError as error:
        assert "candles are required" in str(error)
    else:
        raise AssertionError("Should reject insufficient candles")


class FixedMarketClient:
    async def get_klines(self, request):
        candles = _oscillating()
        return KlineResult(
            market=request.market,
            symbol=request.symbol,
            interval=request.interval,
            candle_count=len(candles),
            candles=candles,
            observed_at=datetime.now(UTC),
        )


def test_pattern_tool_registers_and_runs() -> None:
    async def exercise():
        registry = ToolRegistry()
        register_pattern_tools(registry, FixedMarketClient())
        result = await registry.execute(
            "detect_patterns",
            {"market": "usdm", "symbol": "BTCUSDT", "interval": "1h", "limit": 120},
        )
        return registry, result

    registry, result = asyncio.run(exercise())

    assert result.ok is True
    assert len(result.output.patterns) >= 2
    assert registry.permission_for("detect_patterns") == "read"
