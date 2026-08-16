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
from app.backtest.tools import register_backtest_tools
from app.notes.store import InMemoryNoteStore, PostgresNoteStore
from app.notes.tools import register_note_tools
from app.news.source import UnconfiguredNewsSource
from app.news.tools import register_news_tools
from app.patterns.tools import register_pattern_tools
from app.rag.store import InMemoryKnowledgeStore
from app.rag.tools import register_knowledge_tools
from app.monitoring.monitor import AlertMonitor, ChannelNotifier, FeishuNotifier
from app.monitoring.store import InMemoryAlertStore, PostgresAlertStore
from app.monitoring.tools import register_monitoring_tools
from app.persistence.database import Database
from app.portfolio.store import InMemoryPositionStore, PostgresPositionStore
from app.portfolio.tools import register_portfolio_tools
from app.trading.store import InMemoryTradingStore, PostgresTradingStore
from app.trading.tools import register_trading_tools
from app.persistence.stores import (
    PostgresCheckpointStore,
    PostgresConfirmationStore,
    PostgresConversationStore,
    PostgresRunTraceStore,
)
from app.tools.binance_market import BinanceMarketClient, register_binance_market_tools

SYSTEM_PROMPT = """You are Trading Agent, a cautious cryptocurrency trading research agent.
Use registered tools whenever a claim requires current market or account data.
Never invent prices, news, positions, tool results, or historical statistics.
Clearly distinguish observed facts, calculations, and uncertain interpretation.
Do not promise returns. Real orders, withdrawals, and transfers are unavailable.
When the user asks for trading principles, risk-management rules or technical
analysis methodology, call search_knowledge to cite the built-in knowledge base.
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
    trading: InMemoryTradingStore | PostgresTradingStore
    notes: InMemoryNoteStore | PostgresNoteStore


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
            trading=InMemoryTradingStore(),
            notes=InMemoryNoteStore(),
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
        trading=PostgresTradingStore(database),
        notes=PostgresNoteStore(database),
    )


stores = build_store_bundle(os.getenv("DATABASE_URL", ""))
database = stores.database
conversation_store = stores.conversations
trace_store = stores.traces
confirmation_store = stores.confirmations
checkpoint_store = stores.checkpoints
alert_store = stores.alerts
position_store = stores.positions
trading_store = stores.trading
note_store = stores.notes
feishu_webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
alert_monitor = AlertMonitor(
    store=alert_store,
    notifier=ChannelNotifier(
        FeishuNotifier(feishu_webhook_url) if feishu_webhook_url else None
    ),
)
knowledge_store = InMemoryKnowledgeStore()


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


def build_agent_runner(
    owner_id: str = "default",
    api_key: str | None = None,
    model: str | None = None,
) -> AgentRunner:
    resolved_key = (api_key or os.getenv("DEEPSEEK_API_KEY", "")).strip()
    resolved_model = (model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")).strip()
    provider = (
        DeepSeekProvider(api_key=resolved_key, model=resolved_model)
        if resolved_key
        else UnconfiguredProvider()
    )
    tools = ToolRegistry()
    market_client = BinanceMarketClient()
    register_binance_market_tools(tools, market_client)
    register_backtest_tools(tools, market_client)
    register_pattern_tools(tools, market_client)
    register_monitoring_tools(tools, alert_store, owner_id=owner_id)
    register_portfolio_tools(
        tools,
        position_store,
        market_client,
        owner_id=owner_id,
    )
    register_trading_tools(
        tools,
        trading_store,
        market_client,
        owner_id=owner_id,
    )
    register_note_tools(tools, note_store, owner_id=owner_id)
    register_news_tools(tools, UnconfiguredNewsSource())
    register_knowledge_tools(tools, knowledge_store)
    return AgentRunner(
        provider=provider,
        tools=tools,
        max_steps=8,
        confirmations=confirmation_store,
        checkpoints=checkpoint_store,
    )
