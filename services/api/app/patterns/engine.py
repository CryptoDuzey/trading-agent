from decimal import Decimal

from app.patterns.models import Pattern
from app.tools.binance_market import Candle


def detect_patterns(
    candles: list[Candle],
    *,
    pivot_window: int = 3,
    tolerance: float = 0.02,
) -> list[Pattern]:
    """Detect support/resistance zones and classic double tops/bottoms.

    Pivots are local extremes (a bar whose high/low is the extreme of the
    surrounding ``pivot_window`` bars). Nearby pivots are clustered into a
    single level using a relative tolerance. The result is descriptive, not a
    trade signal.
    """
    minimum = pivot_window * 2 + 3
    if len(candles) < minimum:
        raise ValueError(
            f"At least {minimum} candles are required, got {len(candles)}"
        )

    highs = [Decimal(candle.high) for candle in candles]
    lows = [Decimal(candle.low) for candle in candles]

    pivot_highs: list[tuple[int, Decimal]] = []
    pivot_lows: list[tuple[int, Decimal]] = []
    for index in range(pivot_window, len(candles) - pivot_window):
        if highs[index] == max(highs[index - pivot_window : index + pivot_window + 1]):
            pivot_highs.append((index, highs[index]))
        if lows[index] == min(lows[index - pivot_window : index + pivot_window + 1]):
            pivot_lows.append((index, lows[index]))

    resistances = _cluster([price for _, price in pivot_highs], tolerance)
    supports = _cluster([price for _, price in pivot_lows], tolerance)

    patterns: list[Pattern] = []
    for level in resistances[:3]:
        patterns.append(
            Pattern(
                name="resistance",
                level=_number(level),
                description=f"阻力位约 {_fmt(level)}",
            )
        )
    for level in supports[:3]:
        patterns.append(
            Pattern(
                name="support",
                level=_number(level),
                description=f"支撑位约 {_fmt(level)}",
            )
        )

    double_top = _double_extreme(pivot_highs, pivot_lows, tolerance, kind="top")
    if double_top is not None:
        patterns.append(
            Pattern(
                name="double_top",
                level=_number(double_top),
                description=f"双顶形态，颈线参考约 {_fmt(double_top)}",
            )
        )
    double_bottom = _double_extreme(pivot_lows, pivot_highs, tolerance, kind="bottom")
    if double_bottom is not None:
        patterns.append(
            Pattern(
                name="double_bottom",
                level=_number(double_bottom),
                description=f"双底形态，颈线参考约 {_fmt(double_bottom)}",
            )
        )

    return patterns


def _cluster(values: list[Decimal], tolerance: float) -> list[Decimal]:
    groups: list[list[Decimal]] = []
    for price in values:
        for group in groups:
            mean = sum(group) / Decimal(len(group))
            if abs(mean - price) / mean < Decimal(str(tolerance)):
                group.append(price)
                break
        else:
            groups.append([price])
    levels = [sum(group) / Decimal(len(group)) for group in groups]
    return sorted(set(levels))


def _double_extreme(
    extremes: list[tuple[int, Decimal]],
    opposites: list[tuple[int, Decimal]],
    tolerance: float,
    *,
    kind: str,
) -> Decimal | None:
    """Find two nearby pivot extremes separated by a clear counter-move."""
    for first, second in zip(extremes, extremes[1:], strict=False):
        index_a, price_a = first
        index_b, price_b = second
        if abs(price_a - price_b) / price_a >= Decimal(str(tolerance)):
            continue
        between = [p for idx, p in opposites if index_a < idx < index_b]
        if not between:
            continue
        counter = (
            price_a - min(between) if kind == "top" else max(between) - price_a
        )
        if counter / price_a > Decimal(str(tolerance)):
            return (price_a + price_b) / Decimal(2)
    return None


def _number(value: Decimal) -> float:
    return float(round(value, 8))


def _fmt(value: Decimal) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")
