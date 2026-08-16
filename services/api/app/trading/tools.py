from decimal import Decimal

from pydantic import BaseModel, Field

from app.agent.tools import ToolRegistry
from app.tools.binance_market import GetQuoteInput, MarketQuote
from app.trading.models import (
    CreateTradeReviewInput,
    CreateTradingPlanInput,
    PlaceOrderInput,
    SimulatedOrder,
    TradeReview,
    TradingPlan,
)
from app.trading.store import InMemoryTradingStore, PostgresTradingStore

TradingStore = InMemoryTradingStore | PostgresTradingStore


class ListPlansInput(BaseModel):
    pass


class ListPlansOutput(BaseModel):
    plans: list[TradingPlan]


class ManagePlanInput(BaseModel):
    plan_id: str = Field(min_length=1)


class ListOrdersInput(BaseModel):
    pass


class ListOrdersOutput(BaseModel):
    orders: list[SimulatedOrder]


class ManageOrderInput(BaseModel):
    order_id: str = Field(min_length=1)


class ListReviewsInput(BaseModel):
    pass


class ListReviewsOutput(BaseModel):
    reviews: list[TradeReview]


def _realized_pnl(request: CreateTradeReviewInput) -> Decimal | None:
    if request.exit_price is None:
        return None
    direction = Decimal(1) if request.side == "long" else Decimal(-1)
    return (request.exit_price - request.entry_price) * request.quantity * direction


def register_trading_tools(
    registry: ToolRegistry,
    store: TradingStore,
    market_client: object,
    *,
    owner_id: str,
) -> None:
    async def create_plan(request: CreateTradingPlanInput) -> TradingPlan:
        return await store.create_plan(owner_id, request)

    async def list_plans(_: ListPlansInput) -> ListPlansOutput:
        return ListPlansOutput(plans=await store.list_plans(owner_id))

    async def cancel_plan(request: ManagePlanInput) -> TradingPlan:
        return await store.cancel_plan(owner_id, request.plan_id)

    async def place_order(request: PlaceOrderInput) -> SimulatedOrder:
        if request.order_type == "limit" and request.limit_price is not None:
            filled_price = request.limit_price
        else:
            quote: MarketQuote = await market_client.get_quote(
                GetQuoteInput(market=request.market, symbol=request.symbol)
            )
            filled_price = Decimal(quote.price)
        return await store.place_order(owner_id, request, filled_price=filled_price)

    async def list_orders(_: ListOrdersInput) -> ListOrdersOutput:
        return ListOrdersOutput(orders=await store.list_orders(owner_id))

    async def cancel_order(request: ManageOrderInput) -> SimulatedOrder:
        return await store.cancel_order(owner_id, request.order_id)

    async def create_review(request: CreateTradeReviewInput) -> TradeReview:
        return await store.create_review(
            owner_id,
            request,
            realized_pnl=_realized_pnl(request),
        )

    async def list_reviews(_: ListReviewsInput) -> ListReviewsOutput:
        return ListReviewsOutput(reviews=await store.list_reviews(owner_id))

    registry.register(
        name="create_trading_plan",
        description=(
            "Record a trading plan with entry zone, stop loss, take profit, "
            "position size and the reasoning behind it. Not an order."
        ),
        input_model=CreateTradingPlanInput,
        handler=create_plan,
        permission="write",
    )
    registry.register(
        name="list_trading_plans",
        description="List the current user's trading plans.",
        input_model=ListPlansInput,
        handler=list_plans,
        permission="read",
    )
    registry.register(
        name="cancel_trading_plan",
        description="Cancel one of the current user's trading plans.",
        input_model=ManagePlanInput,
        handler=cancel_plan,
        permission="write",
    )
    registry.register(
        name="place_simulated_order",
        description=(
            "Place a simulated order (paper trade) using the current market "
            "price for market orders. Requires explicit user confirmation."
        ),
        input_model=PlaceOrderInput,
        handler=place_order,
        permission="simulate",
    )
    registry.register(
        name="list_simulated_orders",
        description="List the current user's simulated orders.",
        input_model=ListOrdersInput,
        handler=list_orders,
        permission="read",
    )
    registry.register(
        name="cancel_simulated_order",
        description="Cancel one of the current user's simulated orders.",
        input_model=ManageOrderInput,
        handler=cancel_order,
        permission="write",
    )
    registry.register(
        name="create_trade_review",
        description=(
            "Record a trade review with entry reasoning, outcome and realized "
            "PnL so wins and losses are explained later."
        ),
        input_model=CreateTradeReviewInput,
        handler=create_review,
        permission="write",
    )
    registry.register(
        name="list_trade_reviews",
        description="List the current user's trade reviews.",
        input_model=ListReviewsInput,
        handler=list_reviews,
        permission="read",
    )
