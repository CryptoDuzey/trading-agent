import asyncio

from app.agent.tools import ToolRegistry
from app.rag.store import InMemoryKnowledgeStore, SEED_KNOWLEDGE
from app.rag.tools import register_knowledge_tools


def test_seed_knowledge_is_loaded() -> None:
    async def exercise():
        store = InMemoryKnowledgeStore()
        return await store.list_entries()

    entries = asyncio.run(exercise())
    assert len(entries) == len(SEED_KNOWLEDGE)
    assert len(entries) >= 15


def test_search_ranks_relevant_entries_first() -> None:
    async def exercise():
        store = InMemoryKnowledgeStore()
        return await store.search("如何设置止损控制风险", top_k=3)

    hits = asyncio.run(exercise())

    assert len(hits) >= 1
    assert any("止损" in hit.content or "亏损" in hit.content for hit in hits)


def test_search_is_relevant_for_technical_analysis() -> None:
    async def exercise():
        store = InMemoryKnowledgeStore()
        return await store.search("头肩顶 双底 形态反转", top_k=5)

    hits = asyncio.run(exercise())

    assert any("头肩顶" in hit.content for hit in hits)
    assert any("双底" in hit.content for hit in hits)


def test_add_and_list_knowledge() -> None:
    async def exercise():
        store = InMemoryKnowledgeStore()
        await store.add("突破颈线放量是底部反转确认信号。", source="测试")
        return await store.list_entries()

    entries = asyncio.run(exercise())
    assert len(entries) == len(SEED_KNOWLEDGE) + 1


def test_knowledge_tools_register_and_search() -> None:
    async def exercise():
        store = InMemoryKnowledgeStore()
        registry = ToolRegistry()
        register_knowledge_tools(registry, store)
        result = await registry.execute(
            "search_knowledge",
            {"query": "止损 风险控制", "top_k": 3},
        )
        return registry, result

    registry, result = asyncio.run(exercise())

    assert result.ok is True
    assert len(result.output.results) >= 1
    names = {item["name"] for item in registry.definitions()}
    assert {"search_knowledge", "add_knowledge", "list_knowledge"} <= names
    assert registry.permission_for("search_knowledge") == "read"
    assert registry.permission_for("add_knowledge") == "write"
