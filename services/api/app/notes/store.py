import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.notes.models import CreateResearchNoteInput, ResearchNote
from app.persistence.database import Database
from app.persistence.models import ResearchNoteRow


def _now() -> datetime:
    return datetime.now(UTC)


def _score(note: ResearchNote, query: str) -> int:
    needle = query.strip().lower()
    if not needle:
        return 0
    haystacks = [note.title.lower(), note.content.lower()]
    haystacks.extend(tag.lower() for tag in note.tags)
    return sum(haystack.count(needle) for haystack in haystacks)


class InMemoryNoteStore:
    def __init__(self) -> None:
        self._notes: dict[str, ResearchNote] = {}
        self._lock = asyncio.Lock()

    async def save(
        self,
        owner_id: str,
        request: CreateResearchNoteInput,
    ) -> ResearchNote:
        async with self._lock:
            note = ResearchNote(
                id=str(uuid4()),
                owner_id=owner_id,
                **request.model_dump(),
            )
            self._notes[note.id] = note
            return note.model_copy(deep=True)

    async def list_for_owner(self, owner_id: str) -> list[ResearchNote]:
        async with self._lock:
            notes = [
                note.model_copy(deep=True)
                for note in self._notes.values()
                if note.owner_id == owner_id
            ]
        return sorted(notes, key=lambda note: note.created_at)

    async def search(
        self,
        owner_id: str,
        query: str,
        *,
        limit: int = 10,
    ) -> list[ResearchNote]:
        notes = await self.list_for_owner(owner_id)
        scored = [(note, _score(note, query)) for note in notes]
        ranked = sorted(
            (note for note, score in scored if score > 0),
            key=lambda note: _score(note, query),
            reverse=True,
        )
        return ranked[:limit]


class PostgresNoteStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(
        self,
        owner_id: str,
        request: CreateResearchNoteInput,
    ) -> ResearchNote:
        row = ResearchNoteRow(
            id=str(uuid4()),
            owner_id=owner_id,
            **request.model_dump(),
        )
        async with self.database.sessions.begin() as session:
            session.add(row)
            await session.flush()
            return self._note(row)

    async def list_for_owner(self, owner_id: str) -> list[ResearchNote]:
        async with self.database.sessions() as session:
            rows = (
                await session.execute(
                    select(ResearchNoteRow)
                    .where(ResearchNoteRow.owner_id == owner_id)
                    .order_by(ResearchNoteRow.created_at)
                )
            ).scalars()
            return [self._note(row) for row in rows]

    async def search(
        self,
        owner_id: str,
        query: str,
        *,
        limit: int = 10,
    ) -> list[ResearchNote]:
        notes = await self.list_for_owner(owner_id)
        ranked = sorted(
            (note for note in notes if _score(note, query) > 0),
            key=lambda note: _score(note, query),
            reverse=True,
        )
        return ranked[:limit]

    @staticmethod
    def _note(row: ResearchNoteRow) -> ResearchNote:
        return ResearchNote(
            id=row.id,
            owner_id=row.owner_id,
            title=row.title,
            content=row.content,
            kind=row.kind,  # type: ignore[arg-type]
            tags=list(row.tags),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
