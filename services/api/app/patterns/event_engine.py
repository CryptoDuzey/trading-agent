from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.tools.binance_market import Candle


@dataclass(frozen=True)
class EventImpact:
    baseline_close: float
    forward_closes: list[float]
    change_percent: float
    max_up_percent: float
    max_down_percent: float


def compute_event_impact(
    candles: list[Candle],
    event_time: datetime,
    *,
    forward_bars: int,
) -> EventImpact:
    """Measure a single event's price impact around its timestamp."""
    if not candles:
        raise ValueError("No candles were provided")

    event_ms = int(event_time.timestamp() * 1000)
    before = [candle for candle in candles if candle.open_time <= event_ms]
    after = [candle for candle in candles if candle.open_time > event_ms]
    if not before:
        raise ValueError("No candles before the event time")
    if not after:
        raise ValueError("No candles after the event time")

    baseline = Decimal(before[-1].close)
    forward = after[:forward_bars]

    forward_closes = [float(Decimal(candle.close)) for candle in forward]
    final = Decimal(forward[-1].close) if forward else baseline
    change = (final - baseline) / baseline * Decimal(100)

    max_up = Decimal(0)
    max_down = Decimal(0)
    for candle in forward:
        high = Decimal(candle.high)
        low = Decimal(candle.low)
        max_up = max(max_up, (high - baseline) / baseline * Decimal(100))
        max_down = max(max_down, (baseline - low) / baseline * Decimal(100))

    return EventImpact(
        baseline_close=float(baseline),
        forward_closes=forward_closes,
        change_percent=_number(change),
        max_up_percent=_number(max_up),
        max_down_percent=_number(max_down),
    )


def _number(value: Decimal) -> float:
    return float(round(value, 8))
