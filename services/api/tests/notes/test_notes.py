import asyncio

from app.agent.tools import ToolRegistry
from app.notes.models import CreateResearchNoteInput
from app.notes.store import InMemoryNoteStore
from app.notes.tools import register_note_tools


def _note(**overrides) -> CreateResearchNoteInput:
    values = {
        "title": "BTC 宏观观察",
        "content": "美联储维持利率不变，非农数据好于预期，关注 CPI 对 BTC 的传导。",
        "kind": "macro",
        "tags": ["宏观", "BTC"],
    }
    values.update(overrides)
    return CreateResearchNoteInput(**values)


def test_note_save_and_list_are_owner_scoped() -> None:
    async def exercise():
        store = InMemoryNoteStore()
        note = await store.save("owner-a", _note())
        await store.save("owner-b", _note(title="别人的笔记"))
        return note, await store.list_for_owner("owner-a")

    note, notes = asyncio.run(exercise())

    assert len(notes) == 1
    assert notes[0].id == note.id
    assert notes[0].owner_id == "owner-a"


def test_note_search_ranks_by_keyword_hits() -> None:
    async def exercise():
        store = InMemoryNoteStore()
        await store.save(
            "owner-a",
            _note(title="非农与 BTC", content="非农数据公布后 BTC 波动放大。"),
        )
        await store.save(
            "owner-a",
            _note(title="ETH 技术面", content="ETH 突破关键阻力位。"),
        )
        await store.save(
            "owner-a",
            _note(title="非农传导", content="非农对美元和 BTC 的影响路径。"),
        )
        return await store.search("owner-a", "非农")

    results = asyncio.run(exercise())

    assert len(results) == 2
    assert "非农" in results[0].title


def test_note_tools_register_and_execute() -> None:
    async def exercise():
        store = InMemoryNoteStore()
        registry = ToolRegistry()
        register_note_tools(registry, store, owner_id="owner-a")
        saved = await registry.execute(
            "save_research_note",
            _note().model_dump(mode="json"),
        )
        found = await registry.execute(
            "search_research_notes",
            {"query": "非农"},
        )
        return registry, saved, found

    registry, saved, found = asyncio.run(exercise())

    assert saved.ok is True
    assert found.ok is True
    assert len(found.output.notes) == 1

    save_schema = next(
        item for item in registry.definitions() if item["name"] == "save_research_note"
    )
    assert "owner_id" not in save_schema["parameters"]["properties"]
