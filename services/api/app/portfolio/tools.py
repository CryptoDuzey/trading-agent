from decimal import Decimal

from pydantic import BaseModel, Field

from app.agent.tools import ToolRegistry
from app.portfolio.models import (
    PortfolioRisk,
    Position,
    PositionMark,
    SavePositionInput,
)
from app.portfolio.risk import analyze_portfolio_risk
from app.portfolio.store import InMemoryPositionStore, PostgresPositionStore
from app.tools.binance_market import GetQuoteInput, MarketQuote

PositionStore = InMemoryPositionStore | PostgresPositionStore


class GetPositionsInput(BaseModel):
    pass


class GetPositionsOutput(BaseModel):
    positions: list[Position]


class AnalyzePortfolioRiskInput(BaseModel):
    account_equity: Decimal | str | None = Field(
        default=None,
        description="Optional account equity used to compute portfolio gross leverage.",
    )


def register_portfolio_tools(
    registry: ToolRegistry,
    store: PositionStore,
    market_client: object,
    *,
    owner_id: str,
) -> None:
    async def save_position(request: SavePositionInput) -> Position:
        return await store.save(owner_id, request)

    async def get_positions(_: GetPositionsInput) -> GetPositionsOutput:
        return GetPositionsOutput(positions=await store.list_for_owner(owner_id))

    async def analyze_positions(request: AnalyzePortfolioRiskInput) -> PortfolioRisk:
        positions = await store.list_for_owner(owner_id)
        marks: dict[str, PositionMark] = {}
        for position in positions:
            try:
                quote: MarketQuote = await market_client.get_quote(
                    GetQuoteInput(market=position.market, symbol=position.symbol)
                )
                marks[position.id] = PositionMark(
                    price=quote.price,
                    observed_at=quote.observed_at,
                )
            except Exception:  # noqa: BLE001 - a failed quote becomes a risk flag
                continue
        return analyze_portfolio_risk(
            positions,
            marks,
            account_equity=request.account_equity,
        )

    registry.register(
        name="save_position",
        description=(
            "Record or update one of the user's positions (manual entry). "
            "Ask for market, symbol, side, quantity, entry price, leverage and "
            "optional stop loss before saving."
        ),
        input_model=SavePositionInput,
        handler=save_position,
        permission="write",
    )
    registry.register(
        name="get_positions",
        description="List the current user's recorded positions.",
        input_model=GetPositionsInput,
        handler=get_positions,
        permission="read",
    )
    registry.register(
        name="analyze_portfolio_risk",
        description=(
            "Compute unrealized PnL, per-position and portfolio risk flags from "
            "the user's positions and current Binance quotes. Not a trade order."
        ),
        input_model=AnalyzePortfolioRiskInput,
        handler=analyze_positions,
        permission="read",
    )
