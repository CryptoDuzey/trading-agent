import os
from dataclasses import dataclass

from app.agent.compaction import (
    CompactionResult,
    ConversationCompactor,
    ModelConversationSummarizer,
    SummaryModelProvider,
)
from app.agent.loop import AgentRunner
from app.agent.memory import InMemoryConversationStore
from app.agent.models import AssistantTurn, ModelMessage
from app.agent.permissions import InMemoryCheckpointStore, InMemoryConfirmationStore
from app.agent.providers.deepseek import DeepSeekProvider
from app.agent.tools import ToolRegistry
from app.agent.traces import InMemoryRunTraceStore
from app.monitoring.monitor import AlertMonitor, ChannelNotifier, FeishuNotifier
from app.monitoring.store import InMemoryAlertStore, PostgresAlertStore
from app.monitoring.tools import register_monitoring_tools
from app.persistence.database import Database
from app.portfolio.store import InMemoryPositionStore, PostgresPositionStore
from app.portfolio.tools import register_portfolio_tools
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
    alerts: InMemoryAlertStore | PostgresAlertStore
    positions: InMemoryPositionStore | PostgresPositionStore


def build_store_bundle(database_url: str) -> StoreBundle:
    if not database_url.strip():
        return StoreBundle(
            database=None,
            conversations=InMemoryConversationStore(max_messages=20),
            traces=InMemoryRunTraceStore(),
            confirmations=InMemoryConfirmationStore(),
            checkpoints=InMemoryCheckpointStore(),
            alerts=InMemoryAlertStore(),
            positions=InMemoryPositionStore(),
        )

    database = Database(database_url.strip())
    return StoreBundle(
        database=database,
        conversations=PostgresConversationStore(database, max_messages=20),
        traces=PostgresRunTraceStore(database),
        confirmations=PostgresConfirmationStore(database),
        checkpoints=PostgresCheckpointStore(database),
        alerts=PostgresAlertStore(database),
        positions=PostgresPositionStore(database),
    )


stores = build_store_bundle(os.getenv("DATABASE_URL", ""))
database = stores.database
conversation_store = stores.conversations
trace_store = stores.traces
confirmation_store = stores.confirmations
checkpoint_store = stores.checkpoints
alert_store = stores.alerts
position_store = stores.positions
feishu_webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
alert_monitor = AlertMonitor(
    store=alert_store,
    notifier=ChannelNotifier(
        FeishuNotifier(feishu_webhook_url) if feishu_webhook_url else None
    ),
)


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


async def compact_conversation(
    session_id: str,
    provider: SummaryModelProvider,
) -> CompactionResult:
    if isinstance(provider, UnconfiguredProvider):
        return CompactionResult()
    return await ConversationCompactor(
        conversation_store,
        ModelConversationSummarizer(provider),
    ).compact(session_id)


def build_agent_runner(owner_id: str = "default") -> AgentRunner:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
    provider = (
        DeepSeekProvider(api_key=api_key, model=model)
        if api_key
        else UnconfiguredProvider()
    )
    tools = ToolRegistry()
    market_client = BinanceMarketClient()
    register_binance_market_tools(tools, market_client)
    register_monitoring_tools(tools, alert_store, owner_id=owner_id)
    register_portfolio_tools(
        tools,
        position_store,
        market_client,
        owner_id=owner_id,
    )
    return AgentRunner(
        provider=provider,
        tools=tools,
        max_steps=8,
        confirmations=confirmation_store,
        checkpoints=checkpoint_store,
    )
