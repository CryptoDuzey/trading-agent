import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from app.agent.tools import ToolRegistry
from app.portfolio.models import SavePositionInput
from app.portfolio.store import InMemoryPositionStore
from app.portfolio.tools import register_portfolio_tools
from app.tools.binance_market import MarketQuote


class FixedMarketClient:
    def __init__(self, prices: dict[str, str]) -> None:
        self.prices = prices

    async def get_quote(self, request):
        return MarketQuote(
            market=request.market,
            symbol=request.symbol,
            price=self.prices[request.symbol],
            observed_at=datetime.now(UTC),
        )


def test_position_store_upserts_same_market_symbol_and_side() -> None:
    async def exercise_store():
        store = InMemoryPositionStore()
        first = await store.save(
            "owner-a",
            SavePositionInput(
                market="usdm",
                symbol="btcusdt",
                side="long",
                quantity="0.1",
                entry_price="60000",
                leverage="2",
            ),
        )
        updated = await store.save(
            "owner-a",
            SavePositionInput(
                market="usdm",
                symbol="BTCUSDT",
                side="long",
                quantity="0.2",
                entry_price="61000",
                leverage="3",
            ),
        )
        return first, updated, await store.list_for_owner("owner-a")

    first, updated, positions = asyncio.run(exercise_store())

    assert updated.id == first.id
    assert updated.quantity == Decimal("0.2")
    assert updated.entry_price == Decimal("61000")
    assert len(positions) == 1


def test_position_store_prevents_cross_owner_removal() -> None:
    async def exercise_store():
        store = InMemoryPositionStore()
        position = await store.save(
            "owner-a",
            SavePositionInput(
                market="spot",
                symbol="ETHUSDT",
                side="long",
                quantity="1",
                entry_price="4000",
            ),
        )
        return await store.remove("owner-b", position.id)

    try:
        asyncio.run(exercise_store())
    except KeyError as error:
        assert "Position not found" in str(error)
    else:
        raise AssertionError("Cross-owner removal should fail")


def test_portfolio_tools_save_list_and_analyze_with_current_quotes() -> None:
    async def exercise_tools():
        store = InMemoryPositionStore()
        registry = ToolRegistry()
        register_portfolio_tools(
            registry,
            store,
            FixedMarketClient({"BTCUSDT": "63000"}),
            owner_id="owner-a",
        )
        saved = await registry.execute(
            "save_position",
            {
                "market": "usdm",
                "symbol": "BTCUSDT",
                "side": "long",
                "quantity": "0.1",
                "entry_price": "60000",
                "leverage": "2",
                "stop_loss": "57000",
            },
        )
        listed = await registry.execute("get_positions", {})
        risk = await registry.execute(
            "analyze_portfolio_risk",
            {"account_equity": "5000"},
        )
        return registry, saved, listed, risk

    registry, saved, listed, risk = asyncio.run(exercise_tools())

    assert saved.ok is True
    assert listed.output.positions[0].owner_id == "owner-a"
    assert risk.output.total_unrealized_pnl == 300
    assert risk.output.positions[0].mark_price == 63000
    save_definition = next(
        item for item in registry.definitions() if item["name"] == "save_position"
    )
    assert "owner_id" not in save_definition["parameters"]["properties"]
