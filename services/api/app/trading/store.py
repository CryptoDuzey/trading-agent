import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.persistence.database import Database
from app.persistence.models import (
    SimulatedOrderRow,
    TradeReviewRow,
    TradingPlanRow,
)
from app.trading.models import (
    CreateTradeReviewInput,
    CreateTradingPlanInput,
    PlaceOrderInput,
    SimulatedOrder,
    TradeReview,
    TradingPlan,
)


def _now() -> datetime:
    return datetime.now(UTC)


class InMemoryTradingStore:
    def __init__(self) -> None:
        self._plans: dict[str, TradingPlan] = {}
        self._orders: dict[str, SimulatedOrder] = {}
        self._reviews: dict[str, TradeReview] = {}
        self._lock = asyncio.Lock()

    async def create_plan(
        self,
        owner_id: str,
        request: CreateTradingPlanInput,
    ) -> TradingPlan:
        async with self._lock:
            plan = TradingPlan(
                id=str(uuid4()),
                owner_id=owner_id,
                **request.model_dump(),
            )
            self._plans[plan.id] = plan
            return plan.model_copy(deep=True)

    async def list_plans(self, owner_id: str) -> list[TradingPlan]:
        async with self._lock:
            plans = [
                plan.model_copy(deep=True)
                for plan in self._plans.values()
                if plan.owner_id == owner_id
            ]
        return sorted(plans, key=lambda plan: plan.created_at)

    async def cancel_plan(self, owner_id: str, plan_id: str) -> TradingPlan:
        async with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None or plan.owner_id != owner_id:
                raise KeyError(f"Trading plan not found: {plan_id}")
            plan.status = "cancelled"
            plan.updated_at = _now()
            return plan.model_copy(deep=True)

    async def place_order(
        self,
        owner_id: str,
        request: PlaceOrderInput,
        *,
        filled_price: Decimal | None,
    ) -> SimulatedOrder:
        async with self._lock:
            order = SimulatedOrder(
                id=str(uuid4()),
                owner_id=owner_id,
                market=request.market,
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                order_type=request.order_type,
                limit_price=request.limit_price,
                plan_id=request.plan_id,
                reason=request.reason,
                status="filled",
                filled_price=filled_price,
                filled_at=_now() if filled_price is not None else None,
            )
            self._orders[order.id] = order
            return order.model_copy(deep=True)

    async def list_orders(self, owner_id: str) -> list[SimulatedOrder]:
        async with self._lock:
            orders = [
                order.model_copy(deep=True)
                for order in self._orders.values()
                if order.owner_id == owner_id
            ]
        return sorted(orders, key=lambda order: order.created_at)

    async def cancel_order(self, owner_id: str, order_id: str) -> SimulatedOrder:
        async with self._lock:
            order = self._orders.get(order_id)
            if order is None or order.owner_id != owner_id:
                raise KeyError(f"Simulated order not found: {order_id}")
            order.status = "cancelled"
            return order.model_copy(deep=True)

    async def create_review(
        self,
        owner_id: str,
        request: CreateTradeReviewInput,
        *,
        realized_pnl: Decimal | None,
    ) -> TradeReview:
        async with self._lock:
            review = TradeReview(
                id=str(uuid4()),
                owner_id=owner_id,
                **request.model_dump(),
                realized_pnl=realized_pnl,
            )
            self._reviews[review.id] = review
            return review.model_copy(deep=True)

    async def list_reviews(self, owner_id: str) -> list[TradeReview]:
        async with self._lock:
            reviews = [
                review.model_copy(deep=True)
                for review in self._reviews.values()
                if review.owner_id == owner_id
            ]
        return sorted(reviews, key=lambda review: review.created_at)


class PostgresTradingStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_plan(
        self,
        owner_id: str,
        request: CreateTradingPlanInput,
    ) -> TradingPlan:
        row = TradingPlanRow(
            id=str(uuid4()),
            owner_id=owner_id,
            **request.model_dump(),
            status="planned",
        )
        async with self.database.sessions.begin() as session:
            session.add(row)
            await session.flush()
            return self._plan(row)

    async def list_plans(self, owner_id: str) -> list[TradingPlan]:
        async with self.database.sessions() as session:
            rows = (
                await session.execute(
                    select(TradingPlanRow)
                    .where(TradingPlanRow.owner_id == owner_id)
                    .order_by(TradingPlanRow.created_at)
                )
            ).scalars()
            return [self._plan(row) for row in rows]

    async def cancel_plan(self, owner_id: str, plan_id: str) -> TradingPlan:
        async with self.database.sessions.begin() as session:
            row = (
                await session.execute(
                    select(TradingPlanRow)
                    .where(
                        TradingPlanRow.id == plan_id,
                        TradingPlanRow.owner_id == owner_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"Trading plan not found: {plan_id}")
            row.status = "cancelled"
            row.updated_at = _now()
            await session.flush()
            return self._plan(row)

    async def place_order(
        self,
        owner_id: str,
        request: PlaceOrderInput,
        *,
        filled_price: Decimal | None,
    ) -> SimulatedOrder:
        row = SimulatedOrderRow(
            id=str(uuid4()),
            owner_id=owner_id,
            market=request.market,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
            plan_id=request.plan_id,
            reason=request.reason,
            status="filled",
            filled_price=filled_price,
            filled_at=_now() if filled_price is not None else None,
        )
        async with self.database.sessions.begin() as session:
            session.add(row)
            await session.flush()
            return self._order(row)

    async def list_orders(self, owner_id: str) -> list[SimulatedOrder]:
        async with self.database.sessions() as session:
            rows = (
                await session.execute(
                    select(SimulatedOrderRow)
                    .where(SimulatedOrderRow.owner_id == owner_id)
                    .order_by(SimulatedOrderRow.created_at)
                )
            ).scalars()
            return [self._order(row) for row in rows]

    async def cancel_order(self, owner_id: str, order_id: str) -> SimulatedOrder:
        async with self.database.sessions.begin() as session:
            row = (
                await session.execute(
                    select(SimulatedOrderRow)
                    .where(
                        SimulatedOrderRow.id == order_id,
                        SimulatedOrderRow.owner_id == owner_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"Simulated order not found: {order_id}")
            row.status = "cancelled"
            await session.flush()
            return self._order(row)

    async def create_review(
        self,
        owner_id: str,
        request: CreateTradeReviewInput,
        *,
        realized_pnl: Decimal | None,
    ) -> TradeReview:
        row = TradeReviewRow(
            id=str(uuid4()),
            owner_id=owner_id,
            **request.model_dump(),
            realized_pnl=realized_pnl,
        )
        async with self.database.sessions.begin() as session:
            session.add(row)
            await session.flush()
            return self._review(row)

    async def list_reviews(self, owner_id: str) -> list[TradeReview]:
        async with self.database.sessions() as session:
            rows = (
                await session.execute(
                    select(TradeReviewRow)
                    .where(TradeReviewRow.owner_id == owner_id)
                    .order_by(TradeReviewRow.created_at)
                )
            ).scalars()
            return [self._review(row) for row in rows]

    @staticmethod
    def _plan(row: TradingPlanRow) -> TradingPlan:
        return TradingPlan(
            id=row.id,
            owner_id=row.owner_id,
            market=row.market,  # type: ignore[arg-type]
            symbol=row.symbol,
            side=row.side,  # type: ignore[arg-type]
            entry_low=row.entry_low,
            entry_high=row.entry_high,
            stop_loss=row.stop_loss,
            take_profit=row.take_profit,
            position_size=row.position_size,
            risk_note=row.risk_note,
            status=row.status,  # type: ignore[arg-type]
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _order(row: SimulatedOrderRow) -> SimulatedOrder:
        return SimulatedOrder(
            id=row.id,
            owner_id=row.owner_id,
            market=row.market,  # type: ignore[arg-type]
            symbol=row.symbol,
            side=row.side,  # type: ignore[arg-type]
            quantity=row.quantity,
            order_type=row.order_type,  # type: ignore[arg-type]
            limit_price=row.limit_price,
            plan_id=row.plan_id,
            reason=row.reason,
            status=row.status,  # type: ignore[arg-type]
            filled_price=row.filled_price,
            filled_at=row.filled_at,
            created_at=row.created_at,
        )

    @staticmethod
    def _review(row: TradeReviewRow) -> TradeReview:
        return TradeReview(
            id=row.id,
            owner_id=row.owner_id,
            market=row.market,  # type: ignore[arg-type]
            symbol=row.symbol,
            side=row.side,  # type: ignore[arg-type]
            entry_price=row.entry_price,
            exit_price=row.exit_price,
            quantity=row.quantity,
            entry_reason=row.entry_reason,
            outcome_notes=row.outcome_notes,
            realized_pnl=row.realized_pnl,
            created_at=row.created_at,
        )
