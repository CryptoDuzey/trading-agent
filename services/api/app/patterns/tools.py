from decimal import Decimal

from app.agent.tools import ToolRegistry
from app.patterns.engine import detect_patterns
from app.patterns.event_engine import compute_event_impact
from app.patterns.event_models import EventBacktestInput, EventBacktestResult
from app.patterns.models import DetectPatternsInput, PatternResult
from app.tools.binance_market import GetKlinesInput


def register_pattern_tools(
    registry: ToolRegistry,
    market_client: object,
) -> None:
    async def detect(request: DetectPatternsInput) -> PatternResult:
        klines = await market_client.get_klines(
            GetKlinesInput(
                market=request.market,
                symbol=request.symbol,
                interval=request.interval,
                limit=request.limit,
            )
        )
        patterns = detect_patterns(klines.candles)
        latest_close = (
            Decimal(klines.candles[-1].close) if klines.candles else Decimal(0)
        )
        return PatternResult(
            market=request.market,
            symbol=request.symbol,
            interval=request.interval,
            patterns=patterns,
            latest_close=float(latest_close),
        )

    async def event_backtest(request: EventBacktestInput) -> EventBacktestResult:
        klines = await market_client.get_klines(
            GetKlinesInput(
                market=request.market,
                symbol=request.symbol,
                interval=request.interval,
                limit=request.lookback_bars + request.forward_bars + 10,
            )
        )
        impact = compute_event_impact(
            klines.candles,
            request.event_time,
            forward_bars=request.forward_bars,
        )
        return EventBacktestResult(
            market=request.market,
            symbol=request.symbol,
            interval=request.interval,
            event_time=request.event_time,
            baseline_close=impact.baseline_close,
            forward_closes=impact.forward_closes,
            change_percent=impact.change_percent,
            max_up_percent=impact.max_up_percent,
            max_down_percent=impact.max_down_percent,
        )

    registry.register(
        name="detect_patterns",
        description=(
            "Detect support/resistance levels and classic double top/bottom "
            "patterns from recent Binance candlesticks. Descriptive, not a signal."
        ),
        input_model=DetectPatternsInput,
        handler=detect,
        permission="read",
        timeout_seconds=20,
    )
    registry.register(
        name="run_event_backtest",
        description=(
            "Measure how the price moved after a single macro event at a given "
            "time. Sample size is one, so it describes that event only."
        ),
        input_model=EventBacktestInput,
        handler=event_backtest,
        permission="read",
        timeout_seconds=20,
    )
