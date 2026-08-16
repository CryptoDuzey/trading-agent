from pydantic import BaseModel, Field

from app.agent.tools import ToolRegistry
from app.rag.models import (
    KnowledgeEntry,
    SearchKnowledgeInput,
    SearchKnowledgeResult,
)
from app.rag.store import InMemoryKnowledgeStore


class AddKnowledgeInput(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    source: str = Field(default="manual", max_length=200)


class ListKnowledgeInput(BaseModel):
    pass


class ListKnowledgeOutput(BaseModel):
    entries: list[KnowledgeEntry]


def register_knowledge_tools(
    registry: ToolRegistry,
    store: InMemoryKnowledgeStore,
) -> None:
    async def search(request: SearchKnowledgeInput) -> SearchKnowledgeResult:
        results = await store.search(request.query, request.top_k)
        return SearchKnowledgeResult(
            query=request.query,
            results=results,
        )

    async def add(request: AddKnowledgeInput) -> KnowledgeEntry:
        return await store.add(request.content, request.source)

    async def list_entries(_: ListKnowledgeInput) -> ListKnowledgeOutput:
        return ListKnowledgeOutput(entries=await store.list_entries())

    registry.register(
        name="search_knowledge",
        description=(
            "Search the built-in trading knowledge base for classic trading "
            "principles, technical-analysis rules and risk-management wisdom "
            "relevant to the query. Reference material, not a signal."
        ),
        input_model=SearchKnowledgeInput,
        handler=search,
        permission="read",
    )
    registry.register(
        name="add_knowledge",
        description=(
            "Add a piece of trading knowledge or a research note to the "
            "knowledge base for later retrieval."
        ),
        input_model=AddKnowledgeInput,
        handler=add,
        permission="write",
    )
    registry.register(
        name="list_knowledge",
        description="List all entries in the local trading knowledge base.",
        input_model=ListKnowledgeInput,
        handler=list_entries,
        permission="read",
    )
