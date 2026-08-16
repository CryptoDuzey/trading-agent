from dataclasses import dataclass
from decimal import Decimal

from app.backtest.models import SignalKind
from app.tools.binance_market import Candle


@dataclass(frozen=True)
class SignalStats:
    total_samples: int
    win_rate_percent: float
    average_return_percent: float
    median_return_percent: float
    max_drawdown_percent: float


def compute_signal_stats(
    candles: list[Candle],
    *,
    signal: SignalKind,
    fast_window: int,
    forward_bars: int,
) -> SignalStats:
    """Backtest a moving-average cross signal without look-ahead bias.

    A signal fires on bar ``t`` once its close is known; returns are measured
    from ``t`` to ``t + forward_bars``, so no future close is used to decide
    whether the signal fired. Drawdown uses the low of the bars after entry.
    """
    minimum = fast_window + forward_bars + 1
    if len(candles) < minimum:
        raise ValueError(
            f"At least {minimum} candles are required, got {len(candles)}"
        )

    closes = [Decimal(candle.close) for candle in candles]
    lows = [Decimal(candle.low) for candle in candles]
    highs = [Decimal(candle.high) for candle in candles]
    direction = Decimal(1) if signal == "close_cross_above_ma" else Decimal(-1)

    returns: list[Decimal] = []
    drawdowns: list[Decimal] = []

    for t in range(fast_window, len(candles) - forward_bars):
        previous_ma = sum(closes[t - fast_window : t]) / Decimal(fast_window)
        current_ma = (
            sum(closes[t - fast_window + 1 : t + 1]) / Decimal(fast_window)
        )
        previous_close = closes[t - 1]
        current_close = closes[t]

        if signal == "close_cross_above_ma":
            triggered = previous_close <= previous_ma and current_close > current_ma
        else:
            triggered = previous_close >= previous_ma and current_close < current_ma

        if not triggered:
            continue

        entry = current_close
        exit_price = closes[t + forward_bars]
        returns.append(
            (exit_price - entry) * direction / entry * Decimal(100)
        )

        if direction > 0:
            window = lows[t + 1 : t + forward_bars + 1]
            adverse = (entry - min(window)) if window else Decimal(0)
        else:
            window = highs[t + 1 : t + forward_bars + 1]
            adverse = (max(window) - entry) if window else Decimal(0)
        drawdowns.append(max(Decimal(0), adverse / entry * Decimal(100)))

    if not returns:
        return SignalStats(
            total_samples=0,
            win_rate_percent=0.0,
            average_return_percent=0.0,
            median_return_percent=0.0,
            max_drawdown_percent=0.0,
        )

    wins = sum(1 for value in returns if value > 0)
    win_rate = Decimal(wins) / Decimal(len(returns)) * Decimal(100)
    average = sum(returns) / Decimal(len(returns))
    median = _median(returns)
    max_drawdown = max(drawdowns)

    return SignalStats(
        total_samples=len(returns),
        win_rate_percent=_number(win_rate),
        average_return_percent=_number(average),
        median_return_percent=_number(median),
        max_drawdown_percent=_number(max_drawdown),
    )


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    count = len(ordered)
    if count % 2 == 1:
        return ordered[count // 2]
    return (ordered[count // 2 - 1] + ordered[count // 2]) / Decimal(2)


def _number(value: Decimal) -> float:
    return float(round(value, 8))
