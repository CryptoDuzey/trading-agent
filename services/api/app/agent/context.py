import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agent.models import ModelMessage, ToolExecutionResult


class ContextPolicy(BaseModel):
    max_history_characters: int = Field(default=24_000, ge=1)
    max_history_messages: int = Field(default=20, ge=1)
    max_tool_result_characters: int = Field(default=8_000, ge=200)
    market_data_max_age_seconds: int = Field(default=60, ge=1)


class ContextManager:
    def __init__(
        self,
        policy: ContextPolicy | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy = policy or ContextPolicy()
        self._now = now or (lambda: datetime.now(UTC))

    def select_history(self, history: list[ModelMessage]) -> list[ModelMessage]:
        turns = self._group_turns(history[-self.policy.max_history_messages :])
        selected: list[list[ModelMessage]] = []
        used_characters = 0
        used_messages = 0

        for turn in reversed(turns):
            turn_characters = sum(len(message.content) for message in turn)
            if used_characters + turn_characters > self.policy.max_history_characters:
                break
            if used_messages + len(turn) > self.policy.max_history_messages:
                break
            selected.append(turn)
            used_characters += turn_characters
            used_messages += len(turn)

        return [
            message.model_copy(deep=True)
            for turn in reversed(selected)
            for message in turn
        ]

    def serialize_tool_result(self, result: ToolExecutionResult) -> str:
        payload = result.model_dump(mode="json")
        observed_at = self._extract_observed_at(payload.get("output"))
        context_meta: dict[str, Any] = {
            "truncated": False,
            "is_stale": False,
        }
        if observed_at is not None:
            age_seconds = max(0, int((self._now() - observed_at).total_seconds()))
            context_meta.update(
                {
                    "observed_at": observed_at.isoformat(),
                    "age_seconds": age_seconds,
                    "is_stale": (age_seconds > self.policy.market_data_max_age_seconds),
                }
            )
        payload["context_meta"] = context_meta

        serialized = self._dump(payload)
        if len(serialized) <= self.policy.max_tool_result_characters:
            return serialized

        original_characters = len(serialized)
        compact_payload = {
            "ok": result.ok,
            "error": payload.get("error"),
            "output": {"preview": ""},
            "context_meta": {
                **context_meta,
                "truncated": True,
                "original_characters": original_characters,
            },
        }
        output_json = self._dump(payload.get("output"))
        empty_size = len(self._dump(compact_payload))
        preview_size = max(
            0,
            self.policy.max_tool_result_characters - empty_size,
        )
        compact_payload["output"]["preview"] = output_json[:preview_size]
        serialized = self._dump(compact_payload)
        while len(serialized) > self.policy.max_tool_result_characters and preview_size:
            preview_size = max(
                0,
                preview_size
                - (len(serialized) - self.policy.max_tool_result_characters),
            )
            compact_payload["output"]["preview"] = output_json[:preview_size]
            serialized = self._dump(compact_payload)
        return serialized

    @staticmethod
    def _group_turns(history: list[ModelMessage]) -> list[list[ModelMessage]]:
        turns: list[list[ModelMessage]] = []
        for message in history:
            if message.role == "user" or not turns:
                turns.append([message])
            else:
                turns[-1].append(message)
        return turns

    @staticmethod
    def _extract_observed_at(output: Any) -> datetime | None:
        if not isinstance(output, dict):
            return None
        raw_value = output.get("observed_at")
        if not isinstance(raw_value, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw_value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _dump(payload: Any) -> str:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
