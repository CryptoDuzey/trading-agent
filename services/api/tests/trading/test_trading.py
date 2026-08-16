import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from app.agent.tools import ToolRegistry
from app.tools.binance_market import MarketQuote
from app.trading.models import (
    CreateTradeReviewInput,
    CreateTradingPlanInput,
    PlaceOrderInput,
)
from app.trading.store import InMemoryTradingStore
from app.trading.tools import register_trading_tools


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


def _plan_input(**overrides) -> CreateTradingPlanInput:
    values = {
        "market": "usdm",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_low": "60000",
        "entry_high": "61000",
        "stop_loss": "57000",
        "take_profit": "65000",
        "position_size": "0.1",
        "risk_note": "突破 MA20 后做多",
    }
    values.update(overrides)
    return CreateTradingPlanInput(**values)


def test_trading_plan_crud_and_cancel() -> None:
    async def exercise():
        store = InMemoryTradingStore()
        plan = await store.create_plan("owner-a", _plan_input())
        cancelled = await store.cancel_plan("owner-a", plan.id)
        return plan, await store.list_plans("owner-a"), cancelled

    plan, plans, cancelled = asyncio.run(exercise())

    assert plan.symbol == "BTCUSDT"
    assert len(plans) == 1
    assert cancelled.status == "cancelled"
    assert plans[0].id == plan.id


def test_cross_owner_cancel_plan_is_rejected() -> None:
    async def exercise():
        store = InMemoryTradingStore()
        plan = await store.create_plan("owner-a", _plan_input())
        return await store.cancel_plan("owner-b", plan.id)

    try:
        asyncio.run(exercise())
    except KeyError as error:
        assert "Trading plan not found" in str(error)
    else:
        raise AssertionError("Cross-owner cancel should fail")


def test_entry_high_must_not_be_below_entry_low() -> None:
    try:
        _plan_input(entry_low="61000", entry_high="60000")
    except Exception as error:  # pydantic ValidationError
        assert "entry_high" in str(error)
    else:
        raise AssertionError("Invalid entry range should fail validation")


def test_place_market_order_uses_current_quote() -> None:
    async def exercise():
        store = InMemoryTradingStore()
        order = await store.place_order(
            "owner-a",
            PlaceOrderInput(
                market="usdm",
                symbol="BTCUSDT",
                side="long",
                quantity="0.1",
                order_type="market",
                reason="趋势确认后入场",
            ),
            filled_price=Decimal("63000"),
        )
        return order

    order = asyncio.run(exercise())

    assert order.status == "filled"
    assert order.filled_price == Decimal("63000")
    assert order.filled_at is not None


def test_trade_review_computes_long_and_short_pnl() -> None:
    async def exercise():
        store = InMemoryTradingStore()
        long_review = await store.create_review(
            "owner-a",
            CreateTradeReviewInput(
                market="usdm",
                symbol="BTCUSDT",
                side="long",
                entry_price="60000",
                exit_price="63000",
                quantity="0.1",
                entry_reason="突破做多",
                outcome_notes="符合预期",
            ),
            realized_pnl=Decimal("300"),
        )
        short_review = await store.create_review(
            "owner-a",
            CreateTradeReviewInput(
                market="usdm",
                symbol="ETHUSDT",
                side="short",
                entry_price="4000",
                exit_price="3800",
                quantity="1",
                entry_reason="跌破支撑做空",
                outcome_notes="符合预期",
            ),
            realized_pnl=Decimal("200"),
        )
        return long_review, short_review

    long_review, short_review = asyncio.run(exercise())

    assert long_review.realized_pnl == Decimal("300")
    assert short_review.realized_pnl == Decimal("200")


def test_trading_tools_register_and_execute() -> None:
    async def exercise():
        store = InMemoryTradingStore()
        registry = ToolRegistry()
        register_trading_tools(
            registry,
            store,
            FixedMarketClient({"BTCUSDT": "63000"}),
            owner_id="owner-a",
        )
        plan = await registry.execute(
            "create_trading_plan",
            _plan_input().model_dump(mode="json"),
        )
        order = await registry.execute(
            "place_simulated_order",
            {
                "market": "usdm",
                "symbol": "BTCUSDT",
                "side": "long",
                "quantity": "0.1",
                "order_type": "market",
                "reason": "计划入场",
            },
            confirmed=True,
        )
        review = await registry.execute(
            "create_trade_review",
            {
                "market": "usdm",
                "symbol": "BTCUSDT",
                "side": "long",
                "entry_price": "60000",
                "exit_price": "63000",
                "quantity": "0.1",
                "entry_reason": "突破做多",
                "outcome_notes": "符合预期",
            },
        )
        return registry, plan, order, review

    registry, plan, order, review = asyncio.run(exercise())

    assert plan.ok is True
    assert order.ok is True
    assert order.output.filled_price == Decimal("63000")
    assert review.ok is True
    assert review.output.realized_pnl == Decimal("300")

    names = {item["name"] for item in registry.definitions()}
    assert {
        "create_trading_plan",
        "list_trading_plans",
        "cancel_trading_plan",
        "place_simulated_order",
        "list_simulated_orders",
        "create_trade_review",
        "list_trade_reviews",
    } <= names

    plan_schema = next(
        item for item in registry.definitions() if item["name"] == "create_trading_plan"
    )
    assert "owner_id" not in plan_schema["parameters"]["properties"]
    assert registry.requires_confirmation("place_simulated_order") is True
    assert registry.requires_confirmation("create_trading_plan") is False
