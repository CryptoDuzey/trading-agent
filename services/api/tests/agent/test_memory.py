import asyncio

from app.agent.memory import InMemoryConversationStore


def test_conversation_store_preserves_recent_complete_exchanges() -> None:
    store = InMemoryConversationStore(max_messages=4)

    async def write_and_read():
        await store.append_exchange("session-1", "first question", "first answer")
        await store.append_exchange("session-1", "second question", "second answer")
        await store.append_exchange("session-1", "third question", "third answer")
        return await store.get_recent("session-1")

    messages = asyncio.run(write_and_read())

    assert [message.content for message in messages] == [
        "second question",
        "second answer",
        "third question",
        "third answer",
    ]


def test_conversation_store_keeps_sessions_isolated() -> None:
    store = InMemoryConversationStore()

    async def write_and_read():
        await store.append_exchange("alice", "BTC?", "answer A")
        await store.append_exchange("bob", "ETH?", "answer B")
        return await store.get_recent("alice"), await store.get_recent("bob")

    alice, bob = asyncio.run(write_and_read())

    assert [message.content for message in alice] == ["BTC?", "answer A"]
    assert [message.content for message in bob] == ["ETH?", "answer B"]
