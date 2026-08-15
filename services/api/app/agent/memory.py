import asyncio

from app.agent.models import ModelMessage


class InMemoryConversationStore:
    """Process-local conversation memory used before PostgreSQL is connected."""

    def __init__(self, *, max_messages: int = 20) -> None:
        if max_messages < 2:
            raise ValueError("max_messages must be at least 2")
        self.max_messages = max_messages - (max_messages % 2)
        self._sessions: dict[str, list[ModelMessage]] = {}
        self._lock = asyncio.Lock()

    async def append_exchange(
        self,
        session_id: str,
        user_content: str,
        assistant_content: str,
    ) -> None:
        async with self._lock:
            messages = self._sessions.setdefault(session_id, [])
            messages.extend(
                [
                    ModelMessage(role="user", content=user_content),
                    ModelMessage(role="assistant", content=assistant_content),
                ]
            )
            self._sessions[session_id] = messages[-self.max_messages :]

    async def get_recent(self, session_id: str) -> list[ModelMessage]:
        async with self._lock:
            return [
                message.model_copy(deep=True)
                for message in self._sessions.get(session_id, [])
            ]
