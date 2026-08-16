import asyncio

from pydantic import BaseModel

from app.agent.eval import (
    CATEGORIES,
    EVAL_CASES,
    EvalCase,
    collect_tools_called,
    evaluate_tool_selection,
    run_eval,
    validate_cases,
)
from app.agent.models import AssistantTurn, ToolCall
from app.agent.tools import ToolRegistry


def _registry() -> ToolRegistry:
    class QuoteInput(BaseModel):
        pass

    registry = ToolRegistry()

    async def handler(_: QuoteInput):
        return {"price": "63000"}

    registry.register(
        name="get_market_quote",
        description="quote",
        input_model=QuoteInput,
        handler=handler,
    )
    return registry


def test_eval_cases_are_structurally_valid() -> None:
    assert validate_cases(EVAL_CASES) == []


def test_eval_cases_cover_all_seven_categories() -> None:
    covered = {case.category for case in EVAL_CASES}
    assert covered == set(CATEGORIES)
    assert len(EVAL_CASES) >= 30


def test_evaluate_passes_when_expected_tool_is_called() -> None:
    case = EvalCase("x", "tool_selection", "价格", expected_tools=frozenset({"get_market_quote"}))
    outcome = evaluate_tool_selection(case, frozenset({"get_market_quote"}))
    assert outcome.passed is True


def test_evaluate_fails_when_expected_tool_is_missing() -> None:
    case = EvalCase("x", "tool_selection", "价格", expected_tools=frozenset({"get_market_quote"}))
    outcome = evaluate_tool_selection(case, frozenset({"get_klines"}))
    assert outcome.passed is False
    assert "get_market_quote" in outcome.reason


def test_evaluate_fails_when_forbidden_tool_is_used() -> None:
    case = EvalCase("x", "high_risk_guard", "下单", forbidden_tools=frozenset({"place_simulated_order"}))
    outcome = evaluate_tool_selection(case, frozenset({"place_simulated_order"}))
    assert outcome.passed is False
    assert "forbidden" in outcome.reason


class ScriptedProvider:
    def __init__(self, tool_name: str | None) -> None:
        self.tool_name = tool_name

    async def complete(self, messages, tools):
        if self.tool_name is None:
            return AssistantTurn(content="我没有数据，无法回答。")
        return AssistantTurn(
            content="",
            tool_calls=[ToolCall(id="call-1", name=self.tool_name, arguments={})],
        )


def test_collect_tools_called_reports_invoked_tool() -> None:
    async def exercise():
        return await collect_tools_called(
            ScriptedProvider("get_market_quote"),
            tools=_registry(),
            question="BTC 价格",
            system_prompt="test",
        )

    called = asyncio.run(exercise())
    assert called == frozenset({"get_market_quote"})


def test_run_eval_scores_scripted_provider() -> None:
    async def exercise():
        case = EvalCase(
            "t01",
            "tool_selection",
            "查 BTC 价格",
            expected_tools=frozenset({"get_market_quote"}),
        )
        return await run_eval(
            (case,),
            ScriptedProvider("get_market_quote"),
            tools=_registry(),
            system_prompt="test",
        )

    outcomes = asyncio.run(exercise())
    assert outcomes[0].passed is True
