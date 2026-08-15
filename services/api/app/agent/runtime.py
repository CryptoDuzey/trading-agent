import os

from app.agent.loop import AgentRunner
from app.agent.memory import InMemoryConversationStore
from app.agent.models import AssistantTurn, ModelMessage
from app.agent.providers.deepseek import DeepSeekProvider
from app.agent.tools import ToolRegistry
from app.tools.binance_market import BinanceMarketClient, register_binance_market_tools

SYSTEM_PROMPT = """You are Lobster, a cautious cryptocurrency trading research agent.
Use registered tools whenever a claim requires current market or account data.
Never invent prices, news, positions, tool results, or historical statistics.
Clearly distinguish observed facts, calculations, and uncertain interpretation.
Do not promise returns. Real orders, withdrawals, and transfers are unavailable.
Reply in the user's language and keep the conclusion concise.
"""

conversation_store = InMemoryConversationStore(max_messages=20)


class UnconfiguredProvider:
    async def complete(
        self,
        messages: list[ModelMessage],
        tools: list[dict[str, object]],
    ) -> AssistantTurn:
        return AssistantTurn(
            content=(
                "Agent Harness 已经启动，但尚未配置 DEEPSEEK_API_KEY。"
                "配置密钥后，模型才能理解任务并自主选择工具；在此之前我不会伪造分析。"
            )
        )


def build_agent_runner() -> AgentRunner:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
    provider = (
        DeepSeekProvider(api_key=api_key, model=model)
        if api_key
        else UnconfiguredProvider()
    )
    tools = ToolRegistry()
    register_binance_market_tools(tools, BinanceMarketClient())
    return AgentRunner(
        provider=provider,
        tools=tools,
        max_steps=8,
    )
