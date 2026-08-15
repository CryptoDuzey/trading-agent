import asyncio

from pydantic import BaseModel, Field

from app.agent.tools import ToolRegistry


class QuoteInput(BaseModel):
    symbol: str = Field(min_length=2)


def test_registry_validates_arguments_and_executes_a_tool() -> None:
    registry = ToolRegistry()

    async def get_quote(arguments: QuoteInput) -> dict[str, float | str]:
        return {"symbol": arguments.symbol, "price": 68000.0}

    registry.register(
        name="get_quote",
        description="Get a current market quote",
        input_model=QuoteInput,
        handler=get_quote,
    )

    result = asyncio.run(registry.execute("get_quote", {"symbol": "BTCUSDT"}))

    assert result.ok is True
    assert result.output == {"symbol": "BTCUSDT", "price": 68000.0}
    assert result.error is None
    assert result.duration_ms >= 0


def test_registry_returns_a_structured_error_for_invalid_arguments() -> None:
    registry = ToolRegistry()

    async def get_quote(arguments: QuoteInput) -> dict[str, str]:
        return {"symbol": arguments.symbol}

    registry.register(
        name="get_quote",
        description="Get a current market quote",
        input_model=QuoteInput,
        handler=get_quote,
    )

    result = asyncio.run(registry.execute("get_quote", {"symbol": ""}))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_arguments"
    assert result.output is None


def test_registry_never_executes_an_unknown_tool() -> None:
    registry = ToolRegistry()

    result = asyncio.run(registry.execute("place_real_order", {"symbol": "BTC"}))

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "unknown_tool"
