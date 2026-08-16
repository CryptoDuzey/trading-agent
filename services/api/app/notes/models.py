from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

NoteKind = Literal["research", "macro", "news", "rule", "review"]


class CreateResearchNoteInput(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=20_000)
    kind: NoteKind = "research"
    tags: list[str] = Field(default_factory=list, max_length=20)


class ResearchNote(CreateResearchNoteInput):
    id: str
    owner_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
