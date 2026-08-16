import asyncio
from datetime import UTC, datetime

from app.agent.tools import ToolRegistry
from app.backtest.engine import compute_signal_stats
from app.backtest.tools import register_backtest_tools
from app.tools.binance_market import Candle, KlineResult


def _candles(closes, lows=None):
    if lows is None:
        lows = [c for c in closes]
    return [
        Candle(
            open_time=i,
            close_time=i,
            open=str(c),
            high=str(c),
            low=str(l),
            close=str(c),
            volume="1",
        )
        for i, (c, l) in enumerate(zip(closes, lows, strict=True))
    ]


def test_no_signal_when_price_stays_flat() -> None:
    closes = [100] * 25
    stats = compute_signal_stats(
        _candles(closes),
        signal="close_cross_above_ma",
        fast_window=20,
        forward_bars=2,
    )
    assert stats.total_samples == 0
    assert stats.win_rate_percent == 0.0


def test_cross_above_ma_reports_single_winning_sample() -> None:
    closes = [100] * 20 + [110, 120, 130]
    stats = compute_signal_stats(
        _candles(closes),
        signal="close_cross_above_ma",
        fast_window=20,
        forward_bars=2,
    )
    assert stats.total_samples == 1
    assert stats.win_rate_percent == 100.0
    assert round(stats.average_return_percent, 2) == 18.18
    assert stats.max_drawdown_percent == 0.0


def test_cross_below_ma_reports_losing_sample() -> None:
    closes = [100] * 20 + [90, 95, 100]
    stats = compute_signal_stats(
        _candles(closes),
        signal="close_cross_below_ma",
        fast_window=20,
        forward_bars=2,
    )
    assert stats.total_samples == 1
    assert stats.win_rate_percent == 0.0
    assert round(stats.average_return_percent, 2) == -11.11


def test_drawdown_is_captured_when_price_dips_after_entry() -> None:
    closes = [100] * 20 + [110, 105, 115]
    lows = [99] * 20 + [95, 100, 110]
    stats = compute_signal_stats(
        _candles(closes, lows),
        signal="close_cross_above_ma",
        fast_window=20,
        forward_bars=2,
    )
    assert stats.total_samples == 1
    assert round(stats.max_drawdown_percent, 2) == 9.09


def test_insufficient_candles_raises() -> None:
    try:
        compute_signal_stats(
            _candles([100] * 10),
            signal="close_cross_above_ma",
            fast_window=20,
            forward_bars=2,
        )
    except ValueError as error:
        assert "candles are required" in str(error)
    else:
        raise AssertionError("Should reject insufficient candles")


class FixedMarketClient:
    async def get_klines(self, request):
        closes = [100] * 20 + [110, 120, 130]
        candles = _candles(closes)
        return KlineResult(
            market=request.market,
            symbol=request.symbol,
            interval=request.interval,
            candle_count=len(candles),
            candles=candles,
            observed_at=datetime.now(UTC),
        )


def test_backtest_tool_registers_and_runs() -> None:
    async def exercise():
        registry = ToolRegistry()
        register_backtest_tools(registry, FixedMarketClient())
        result = await registry.execute(
            "run_signal_backtest",
            {
                "market": "usdm",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "signal": "close_cross_above_ma",
                "fast_window": 20,
                "forward_bars": 2,
                "limit": 500,
            },
        )
        return registry, result

    registry, result = asyncio.run(exercise())

    assert result.ok is True
    assert result.output.total_samples == 1
    assert result.output.win_rate_percent == 100.0
    assert registry.permission_for("run_signal_backtest") == "read"
