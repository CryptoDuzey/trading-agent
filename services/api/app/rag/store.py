import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from app.rag.embed import TfidfIndex
from app.rag.models import KnowledgeEntry, KnowledgeHit

SEED_KNOWLEDGE: list[tuple[str, str]] = [
    ("趋势是你的朋友，顺势交易，不要逆势抄底摸顶。", "利弗莫尔《股票作手回忆录》"),
    ("截断亏损，让利润奔跑；小亏大赚是长期盈利的核心。", "华尔街经典格言"),
    ("永远不要在没有止损的情况下进场，先想好离场再入场。", "交易风控通则"),
    ("仓位决定心态：单笔风险控制在总资金的 1%～2%，才拿得住单子。", "海龟交易法则"),
    ("价格突破关键支撑或阻力并伴随成交量放大，趋势延续的概率更高。", "技术分析经典"),
    ("支撑位是过去买盘集中成交的区域，跌破后常转为阻力；反之亦然。", "技术分析经典"),
    ("均线多头排列且价格回踩均线不破，是趋势中较安全的顺势入场点。", "技术分析经典"),
    ("RSI 高于 70 属于超买、低于 30 属于超卖，但强趋势中指标可以持续钝化。", "技术分析经典"),
    ("消息面驱动的是短期波动，趋势和资金面决定中期方向。", "交易心法"),
    ("利好出尽常是利空，利空出尽常是利好，关键看价格如何反应。", "交易心法"),
    ("不要在亏损的仓位上加仓摊薄成本，这会让小错变成大错。", "交易纪律"),
    ("交易计划要在进场前写好：入场理由、止损、止盈、仓位，缺一不可。", "交易纪律"),
    ("市场永远是对的，错的是你的判断；及时认错比坚持正确更重要。", "交易心理"),
    ("过度交易是亏损的常见来源；只做自己有把握、符合系统的机会。", "交易心理"),
    ("复盘每一笔交易，区分是运气还是系统优势，才能持续改进。", "交易心理"),
    ("波动率放大时要降低仓位，避免在剧烈波动中被扫损出局。", "海龟交易法则"),
    ("财报季注意业绩与预期的差值，超预期或不及预期决定短期方向。", "基本面分析"),
    ("机构资金往往在放量突破或缩量回踩时进场，注意量价配合。", "量价分析"),
    ("头肩顶形态在上升趋势末端出现，跌破颈线是趋势反转的警示信号。", "技术分析经典"),
    ("双底形态在下跌趋势末端出现，突破颈线并放量是底部反转的确认。", "技术分析经典"),
]


class InMemoryKnowledgeStore:
    """Local knowledge base seeded with classic trading principles."""

    def __init__(self, entries: list[KnowledgeEntry] | None = None) -> None:
        self._entries: dict[str, KnowledgeEntry] = {}
        self._lock = asyncio.Lock()
        if entries:
            for entry in entries:
                self._entries[entry.id] = entry
        else:
            for content, source in SEED_KNOWLEDGE:
                entry = KnowledgeEntry(
                    id=str(uuid4()),
                    content=content,
                    source=source,
                    created_at=datetime.now(UTC),
                )
                self._entries[entry.id] = entry

    async def add(self, content: str, source: str = "manual") -> KnowledgeEntry:
        entry = KnowledgeEntry(
            id=str(uuid4()),
            content=content,
            source=source,
            created_at=datetime.now(UTC),
        )
        async with self._lock:
            self._entries[entry.id] = entry
        return entry.model_copy(deep=True)

    async def list_entries(self) -> list[KnowledgeEntry]:
        async with self._lock:
            entries = [entry.model_copy(deep=True) for entry in self._entries.values()]
        return sorted(entries, key=lambda entry: entry.created_at)

    async def search(self, query: str, top_k: int) -> list[KnowledgeHit]:
        entries = await self.list_entries()
        if not entries:
            return []
        index = TfidfIndex([entry.content for entry in entries])
        hits: list[KnowledgeHit] = []
        for position, score in index.search(query, top_k):
            entry = entries[position]
            hits.append(
                KnowledgeHit(
                    content=entry.content,
                    source=entry.source,
                    score=round(score, 4),
                )
            )
        return hits
