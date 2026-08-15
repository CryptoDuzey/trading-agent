from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 5,
        max_overflow: int = 5,
    ) -> None:
        if not url:
            raise ValueError("Database URL is required")
        connect_args = (
            {
                "server_settings": {
                    "idle_in_transaction_session_timeout": "30000",
                }
            }
            if url.startswith("postgresql+asyncpg")
            else {"options": "-c idle_in_transaction_session_timeout=30000"}
        )
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args=connect_args,
        )
        self.sessions = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    async def dispose(self) -> None:
        await self.engine.dispose()
