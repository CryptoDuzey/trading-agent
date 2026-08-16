import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal, TypedDict
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.agent.loop import AgentRunner
from app.agent.runtime import (
    SYSTEM_PROMPT,
    alert_monitor,
    alert_store,
    build_agent_runner,
    compact_conversation,
    conversation_store,
    database,
    trace_store,
)
from app.agent.traces import RunTrace
from app.monitoring.models import AlertTask, CreateAlertInput

logger = logging.getLogger(__name__)


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: Literal["lobster-api"]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    stop_event = asyncio.Event()
    monitor_task: asyncio.Task[None] | None = None
    monitor_enabled = os.getenv("ENABLE_ALERT_MONITOR", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    if monitor_enabled:
        poll_seconds = float(os.getenv("ALERT_POLL_SECONDS", "5"))
        monitor_task = asyncio.create_task(
            alert_monitor.run_forever(stop_event, poll_seconds=poll_seconds)
        )
    try:
        yield
    finally:
        stop_event.set()
        if monitor_task is not None:
            await monitor_task
        if database is not None:
            await database.dispose()


app = FastAPI(title="Lobster Trading Agent API", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""
    api_key: str = ""
    model: str = ""

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


class AlertCreateRequest(CreateAlertInput):
    owner_id: str = Field(min_length=1, max_length=100)


def as_sse(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


async def stream_agent_reply(
    message: str,
    session_id: str,
    api_key: str = "",
    model: str = "",
) -> AsyncIterator[str]:
    runner = build_agent_runner(
        session_id,
        api_key=api_key.strip() or None,
        model=model.strip() or None,
    )
    history = await conversation_store.get_recent(session_id)
    assistant_parts: list[str] = []
    completed = False
    yield as_sse("session", {"session_id": session_id})
    async for agent_event in runner.stream(
        user_message=message,
        system_prompt=SYSTEM_PROMPT,
        history=history,
    ):
        await trace_store.append(session_id, agent_event)
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
        try:
            await compact_conversation(session_id, runner.provider)
        except Exception:  # noqa: BLE001 - compaction must not fail a completed reply
            logger.exception("Conversation compaction failed for %s", session_id)
    yield as_sse("done", {})


async def stream_agent_resume(
    runner: AgentRunner,
    confirmation_id: str,
    session_id: str,
    original_user_message: str,
) -> AsyncIterator[str]:
    assistant_parts: list[str] = []
    completed = False
    yield as_sse("session", {"session_id": session_id})
    async for agent_event in runner.resume(confirmation_id):
        await trace_store.append(session_id, agent_event)
        yield as_sse("agent_event", agent_event.model_dump(mode="json"))
        if agent_event.type == "answer_delta":
            assistant_parts.append(str(agent_event.data["content"]))
            yield as_sse("delta", {"content": agent_event.data["content"]})
        elif agent_event.type == "run_failed":
            yield as_sse(
                "error",
                {
                    "code": agent_event.data.get("code", "agent_failed"),
                    "content": agent_event.data.get(
                        "message",
                        "Agent 恢复执行失败。",
                    ),
                },
            )
        elif agent_event.type == "run_completed":
            completed = True
    if completed and assistant_parts:
        await conversation_store.append_exchange(
            session_id,
            original_user_message,
            "".join(assistant_parts),
        )
        try:
            await compact_conversation(session_id, runner.provider)
        except Exception:  # noqa: BLE001 - compaction must not fail a completed reply
            logger.exception("Conversation compaction failed for %s", session_id)
    yield as_sse("done", {})


@app.get("/health")
async def health() -> HealthResponse:
    return {
        "status": "ok",
        "service": "lobster-api",
    }


@app.get("/api/runs/{run_id}")
async def get_run_trace(run_id: str) -> RunTrace:
    trace = await trace_store.get(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Run trace not found")
    return trace


@app.post("/api/confirmations/{confirmation_id}/approve")
async def approve_confirmation(confirmation_id: str) -> StreamingResponse:
    runner = build_agent_runner()
    checkpoint = await runner.checkpoints.get(confirmation_id)
    if checkpoint is None:
        raise HTTPException(status_code=404, detail="Confirmation not found")
    trace = await trace_store.get(checkpoint.run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Run trace not found")
    runner = build_agent_runner(trace.session_id)
    try:
        await runner.confirmations.approve(confirmation_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    original_user_message = str(trace.events[0].data.get("user_message", ""))
    return StreamingResponse(
        stream_agent_resume(
            runner,
            confirmation_id,
            trace.session_id,
            original_user_message,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat/stream")
async def stream_chat(request: ChatRequest) -> StreamingResponse:
    session_id = request.session_id or str(uuid4())
    return StreamingResponse(
        stream_agent_reply(
            request.message,
            session_id,
            request.api_key,
            request.model,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/alerts", response_model=AlertTask, status_code=201)
async def create_alert(request: AlertCreateRequest) -> AlertTask:
    values = request.model_dump(exclude={"owner_id"})
    return await alert_store.create(
        request.owner_id,
        CreateAlertInput.model_validate(values),
    )


@app.get("/api/alerts", response_model=list[AlertTask])
async def list_alerts(owner_id: str) -> list[AlertTask]:
    return await alert_store.list_for_owner(owner_id)


async def change_alert_status(
    owner_id: str,
    task_id: str,
    status: str,
) -> AlertTask:
    try:
        return await alert_store.set_status(
            owner_id,
            task_id,
            status,  # type: ignore[arg-type]
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Alert task not found") from error


@app.post("/api/alerts/{task_id}/pause", response_model=AlertTask)
async def pause_alert(task_id: str, owner_id: str) -> AlertTask:
    return await change_alert_status(owner_id, task_id, "paused")


@app.post("/api/alerts/{task_id}/resume", response_model=AlertTask)
async def resume_alert(task_id: str, owner_id: str) -> AlertTask:
    return await change_alert_status(owner_id, task_id, "active")
