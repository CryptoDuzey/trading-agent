import json
from collections.abc import AsyncIterator
from typing import Any, Literal, TypedDict
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from app.agent.runtime import SYSTEM_PROMPT, build_agent_runner, conversation_store


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: Literal["lobster-api"]


app = FastAPI(title="Lobster Trading Agent API")


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("message must not be blank")
        return cleaned

    @field_validator("session_id")
    @classmethod
    def normalize_session_id(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) > 100:
            raise ValueError("session_id is too long")
        return cleaned


def as_sse(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


async def stream_agent_reply(
    message: str,
    session_id: str,
) -> AsyncIterator[str]:
    runner = build_agent_runner()
    history = await conversation_store.get_recent(session_id)
    assistant_parts: list[str] = []
    completed = False
    yield as_sse("session", {"session_id": session_id})
    async for agent_event in runner.stream(
        user_message=message,
        system_prompt=SYSTEM_PROMPT,
        history=history,
    ):
        yield as_sse(
            "agent_event",
            agent_event.model_dump(mode="json"),
        )
        if agent_event.type == "answer_delta":
            assistant_parts.append(str(agent_event.data["content"]))
            yield as_sse(
                "delta",
                {"content": agent_event.data["content"]},
            )
        elif agent_event.type == "run_failed":
            yield as_sse(
                "error",
                {
                    "code": agent_event.data.get("code", "agent_failed"),
                    "content": agent_event.data.get(
                        "message",
                        "Agent 运行失败，请稍后重试。",
                    ),
                },
            )
        elif agent_event.type == "run_completed":
            completed = True
    if completed and assistant_parts:
        await conversation_store.append_exchange(
            session_id,
            message,
            "".join(assistant_parts),
        )
    yield as_sse("done", {})


@app.get("/health")
async def health() -> HealthResponse:
    return {
        "status": "ok",
        "service": "lobster-api",
    }


@app.post("/api/chat/stream")
async def stream_chat(request: ChatRequest) -> StreamingResponse:
    session_id = request.session_id or str(uuid4())
    return StreamingResponse(
        stream_agent_reply(request.message, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
