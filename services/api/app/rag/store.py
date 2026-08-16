import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from app.rag.embed import TfidfIndex
from app.rag.models import KnowledgeEntry, KnowledgeHit
from app.rag.seed import SEED_KNOWLEDGE


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
