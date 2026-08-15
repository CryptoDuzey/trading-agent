from app.agent.memory import InMemoryConversationStore
from app.agent.runtime import build_store_bundle
from app.monitoring.store import InMemoryAlertStore, PostgresAlertStore
from app.persistence.stores import (
    PostgresCheckpointStore,
    PostgresConfirmationStore,
    PostgresConversationStore,
    PostgresRunTraceStore,
)


def test_runtime_uses_memory_stores_without_database_url() -> None:
    stores = build_store_bundle("")

    assert stores.database is None
    assert isinstance(stores.conversations, InMemoryConversationStore)
    assert isinstance(stores.alerts, InMemoryAlertStore)


def test_runtime_uses_postgres_stores_with_database_url() -> None:
    stores = build_store_bundle(
        "postgresql+asyncpg://lobster:password@127.0.0.1:5432/lobster"
    )

    assert stores.database is not None
    assert isinstance(stores.conversations, PostgresConversationStore)
    assert isinstance(stores.traces, PostgresRunTraceStore)
    assert isinstance(stores.confirmations, PostgresConfirmationStore)
    assert isinstance(stores.checkpoints, PostgresCheckpointStore)
    assert isinstance(stores.alerts, PostgresAlertStore)
