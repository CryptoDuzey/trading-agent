from datetime import UTC, datetime

from app.patterns.event_engine import compute_event_impact
from app.tools.binance_market import Candle

HOUR = 3_600_000
BASE = 1_700_000_000_000


def _timed_candles() -> list[Candle]:
    candles = []
    for i in range(6):
        candles.append(_candle(BASE + i * HOUR, close=100, high=101, low=99))
    candles.append(_candle(BASE + 6 * HOUR, close=105, high=107, low=103))
    candles.append(_candle(BASE + 7 * HOUR, close=108, high=109, low=104))
    candles.append(_candle(BASE + 8 * HOUR, close=110, high=112, low=106))
    return candles


def _candle(open_time: int, *, close: int, high: int, low: int) -> Candle:
    return Candle(
        open_time=open_time,
        close_time=open_time + HOUR,
        open=str(close),
        high=str(high),
        low=str(low),
        close=str(close),
        volume="1",
    )


def _event_time() -> datetime:
    # 1ms before the 7th candle opens, i.e. inside the 6th bar.
    return datetime.fromtimestamp((BASE + 6 * HOUR - 1) / 1000, tz=UTC)


def test_event_impact_measures_change_and_swing() -> None:
    impact = compute_event_impact(
        _timed_candles(),
        _event_time(),
        forward_bars=3,
    )

    assert impact.baseline_close == 100
    assert impact.forward_closes == [105.0, 108.0, 110.0]
    assert round(impact.change_percent, 2) == 10.0
    assert round(impact.max_up_percent, 2) == 12.0
    assert impact.max_down_percent == 0.0


def test_event_impact_requires_candles_on_both_sides() -> None:
    candles = [_candle(BASE, close=100, high=101, low=99)]
    try:
        compute_event_impact(candles, _event_time(), forward_bars=3)
    except ValueError as error:
        assert "No candles after the event time" in str(error)
    else:
        raise AssertionError("Should reject an event with no later candles")
