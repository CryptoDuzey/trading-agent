import os
from dataclasses import dataclass

from app.agent.loop import AgentRunner
from app.agent.memory import InMemoryConversationStore
from app.agent.models import AssistantTurn, ModelMessage
from app.agent.permissions import InMemoryCheckpointStore, InMemoryConfirmationStore
from app.agent.providers.deepseek import DeepSeekProvider
from app.agent.tools import ToolRegistry
from app.agent.traces import InMemoryRunTraceStore
from app.persistence.database import Database
from app.persistence.stores import (
    PostgresCheckpointStore,
    PostgresConfirmationStore,
    PostgresConversationStore,
    PostgresRunTraceStore,
)
from app.tools.binance_market import BinanceMarketClient, register_binance_market_tools

SYSTEM_PROMPT = """You are Lobster, a cautious cryptocurrency trading research agent.
Use registered tools whenever a claim requires current market or account data.
Never invent prices, news, positions, tool results, or historical statistics.
Clearly distinguish observed facts, calculations, and uncertain interpretation.
Do not promise returns. Real orders, withdrawals, and transfers are unavailable.
Reply in the user's language and keep the conclusion concise.
"""


@dataclass(frozen=True)
class StoreBundle:
    database: Database | None
    conversations: InMemoryConversationStore | PostgresConversationStore
    traces: InMemoryRunTraceStore | PostgresRunTraceStore
    confirmations: InMemoryConfirmationStore | PostgresConfirmationStore
    checkpoints: InMemoryCheckpointStore | PostgresCheckpointStore


def build_store_bundle(database_url: str) -> StoreBundle:
    if not database_url.strip():
        return StoreBundle(
            database=None,
            conversations=InMemoryConversationStore(max_messages=20),
            traces=InMemoryRunTraceStore(),
            confirmations=InMemoryConfirmationStore(),
            checkpoints=InMemoryCheckpointStore(),
        )

    database = Database(database_url.strip())
    return StoreBundle(
        database=database,
        conversations=PostgresConversationStore(database, max_messages=20),
        traces=PostgresRunTraceStore(database),
        confirmations=PostgresConfirmationStore(database),
        checkpoints=PostgresCheckpointStore(database),
    )


stores = build_store_bundle(os.getenv("DATABASE_URL", ""))
database = stores.database
conversation_store = stores.conversations
trace_store = stores.traces
confirmation_store = stores.confirmations
checkpoint_store = stores.checkpoints


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
        confirmations=confirmation_store,
        checkpoints=checkpoint_store,
    )
