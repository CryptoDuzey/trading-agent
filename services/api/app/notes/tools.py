from pydantic import BaseModel, Field

from app.agent.tools import ToolRegistry
from app.notes.models import CreateResearchNoteInput, ResearchNote
from app.notes.store import InMemoryNoteStore, PostgresNoteStore

NoteStore = InMemoryNoteStore | PostgresNoteStore


class ListNotesInput(BaseModel):
    pass


class ListNotesOutput(BaseModel):
    notes: list[ResearchNote]


class SearchNotesInput(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=10, ge=1, le=50)


def register_note_tools(
    registry: ToolRegistry,
    store: NoteStore,
    *,
    owner_id: str,
) -> None:
    async def save_note(request: CreateResearchNoteInput) -> ResearchNote:
        return await store.save(owner_id, request)

    async def list_notes(_: ListNotesInput) -> ListNotesOutput:
        return ListNotesOutput(notes=await store.list_for_owner(owner_id))

    async def search_notes(request: SearchNotesInput) -> ListNotesOutput:
        return ListNotesOutput(
            notes=await store.search(owner_id, request.query, limit=request.limit)
        )

    registry.register(
        name="save_research_note",
        description=(
            "Save a research note, macro observation, news summary, trading rule "
            "or review excerpt for later retrieval. Text only; do not store prices."
        ),
        input_model=CreateResearchNoteInput,
        handler=save_note,
        permission="write",
    )
    registry.register(
        name="list_research_notes",
        description="List the current user's saved research notes.",
        input_model=ListNotesInput,
        handler=list_notes,
        permission="read",
    )
    registry.register(
        name="search_research_notes",
        description="Search the current user's notes by keyword and rank by relevance.",
        input_model=SearchNotesInput,
        handler=search_notes,
        permission="read",
    )
