from app.agent.tools import ToolRegistry
from app.backtest.engine import compute_signal_stats
from app.backtest.models import SignalBacktestInput, SignalBacktestResult
from app.tools.binance_market import GetKlinesInput


def register_backtest_tools(
    registry: ToolRegistry,
    market_client: object,
) -> None:
    async def run_backtest(request: SignalBacktestInput) -> SignalBacktestResult:
        klines = await market_client.get_klines(
            GetKlinesInput(
                market=request.market,
                symbol=request.symbol,
                interval=request.interval,
                limit=request.limit,
            )
        )
        stats = compute_signal_stats(
            klines.candles,
            signal=request.signal,
            fast_window=request.fast_window,
            forward_bars=request.forward_bars,
        )
        return SignalBacktestResult(
            market=request.market,
            symbol=request.symbol,
            interval=request.interval,
            signal=request.signal,
            fast_window=request.fast_window,
            forward_bars=request.forward_bars,
            total_samples=stats.total_samples,
            win_rate_percent=stats.win_rate_percent,
            average_return_percent=stats.average_return_percent,
            median_return_percent=stats.median_return_percent,
            max_drawdown_percent=stats.max_drawdown_percent,
        )

    registry.register(
        name="run_signal_backtest",
        description=(
            "Backtest a simple moving-average cross signal over historical "
            "Binance candlesticks and report sample count, win rate, average "
            "return and drawdown. Descriptive only, not a forecast."
        ),
        input_model=SignalBacktestInput,
        handler=run_backtest,
        permission="read",
        timeout_seconds=25,
    )
