from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeEntry(BaseModel):
    id: str
    content: str = Field(min_length=1, max_length=20_000)
    source: str = Field(default="manual", max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SearchKnowledgeInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeHit(BaseModel):
    content: str
    source: str
    score: float


class SearchKnowledgeResult(BaseModel):
    query: str
    results: list[KnowledgeHit]
    source: Literal["local_knowledge_base"] = "local_knowledge_base"
    limitation: str = (
        "检索结果来自本地内置的交易知识库，按文本相似度排序，"
        "只作为参考观点，不是投资建议。"
    )
