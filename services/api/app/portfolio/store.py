import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.persistence.database import Database
from app.persistence.models import PositionRow
from app.portfolio.models import Position, SavePositionInput


class InMemoryPositionStore:
    """Process-local position store used before PostgreSQL persistence exists."""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}
        self._lock = asyncio.Lock()

    async def save(
        self,
        owner_id: str,
        request: SavePositionInput,
    ) -> Position:
        now = datetime.now(UTC)
        async with self._lock:
            existing = next(
                (
                    position
                    for position in self._positions.values()
                    if position.owner_id == owner_id
                    and position.market == request.market
                    and position.symbol == request.symbol
                    and position.side == request.side
                ),
                None,
            )
            if existing is not None:
                existing.quantity = request.quantity
                existing.entry_price = request.entry_price
                existing.leverage = request.leverage
                existing.stop_loss = request.stop_loss
                existing.updated_at = now
                return existing.model_copy(deep=True)

            position = Position(
                id=str(uuid4()),
                owner_id=owner_id,
                **request.model_dump(),
                opened_at=now,
                updated_at=now,
            )
            self._positions[position.id] = position
            return position.model_copy(deep=True)

    async def list_for_owner(self, owner_id: str) -> list[Position]:
        async with self._lock:
            positions = [
                position.model_copy(deep=True)
                for position in self._positions.values()
                if position.owner_id == owner_id
            ]
        return sorted(positions, key=lambda position: position.opened_at)

    async def remove(self, owner_id: str, position_id: str) -> None:
        async with self._lock:
            position = self._positions.get(position_id)
            if position is None or position.owner_id != owner_id:
                raise KeyError(f"Position not found: {position_id}")
            del self._positions[position_id]


class PostgresPositionStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(
        self,
        owner_id: str,
        request: SavePositionInput,
    ) -> Position:
        now = datetime.now(UTC)
        async with self.database.sessions.begin() as session:
            row = (
                await session.execute(
                    select(PositionRow)
                    .where(
                        PositionRow.owner_id == owner_id,
                        PositionRow.market == request.market,
                        PositionRow.symbol == request.symbol,
                        PositionRow.side == request.side,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is not None:
                row.quantity = request.quantity
                row.entry_price = request.entry_price
                row.leverage = request.leverage
                row.stop_loss = request.stop_loss
                row.updated_at = now
                await session.flush()
                return self._position(row)

            row = PositionRow(
                id=str(uuid4()),
                owner_id=owner_id,
                market=request.market,
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                entry_price=request.entry_price,
                leverage=request.leverage,
                stop_loss=request.stop_loss,
                source="manual",
                opened_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            return self._position(row)

    async def list_for_owner(self, owner_id: str) -> list[Position]:
        async with self.database.sessions() as session:
            rows = (
                await session.execute(
                    select(PositionRow)
                    .where(PositionRow.owner_id == owner_id)
                    .order_by(PositionRow.opened_at)
                )
            ).scalars()
            return [self._position(row) for row in rows]

    async def remove(self, owner_id: str, position_id: str) -> None:
        async with self.database.sessions.begin() as session:
            row = (
                await session.execute(
                    select(PositionRow)
                    .where(
                        PositionRow.id == position_id,
                        PositionRow.owner_id == owner_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"Position not found: {position_id}")
            await session.delete(row)

    @staticmethod
    def _position(row: PositionRow) -> Position:
        return Position(
            id=row.id,
            owner_id=row.owner_id,
            market=row.market,  # type: ignore[arg-type]
            symbol=row.symbol,
            side=row.side,  # type: ignore[arg-type]
            quantity=row.quantity,
            entry_price=row.entry_price,
            leverage=row.leverage,
            stop_loss=row.stop_loss,
            source=row.source,  # type: ignore[arg-type]
            opened_at=row.opened_at,
            updated_at=row.updated_at,
        )
