from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AssistantTurn(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: TokenUsage | None = None


class ToolError(BaseModel):
    code: Literal[
        "unknown_tool",
        "invalid_arguments",
        "execution_failed",
        "timeout",
    ]
    message: str


class ToolExecutionResult(BaseModel):
    ok: bool
    output: Any | None = None
    error: ToolError | None = None
    duration_ms: float = 0


AgentEventType = Literal[
    "run_started",
    "model_started",
    "tool_started",
    "tool_finished",
    "answer_delta",
    "run_completed",
    "run_failed",
]


class AgentEvent(BaseModel):
    type: AgentEventType
    run_id: str
    sequence: int
    step: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
