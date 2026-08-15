import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.models import ToolError, ToolExecutionResult

ToolHandler = Callable[[BaseModel], Any | Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler
    timeout_seconds: float

    def definition(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        input_model: type[BaseModel],
        handler: ToolHandler,
        timeout_seconds: float = 20,
    ) -> None:
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = RegisteredTool(
            name=name,
            description=description,
            input_model=input_model,
            handler=handler,
            timeout_seconds=timeout_seconds,
        )

    def definitions(self) -> list[dict[str, object]]:
        return [tool.definition() for tool in self._tools.values()]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolExecutionResult:
        started_at = perf_counter()
        tool = self._tools.get(name)
        if tool is None:
            return self._failure(
                started_at,
                code="unknown_tool",
                message=f"Tool is not registered: {name}",
            )

        try:
            validated = tool.input_model.model_validate(arguments)
        except ValidationError as error:
            return self._failure(
                started_at,
                code="invalid_arguments",
                message=str(error),
            )

        try:
            value = tool.handler(validated)
            if inspect.isawaitable(value):
                value = await asyncio.wait_for(
                    value,
                    timeout=tool.timeout_seconds,
                )
            return ToolExecutionResult(
                ok=True,
                output=value,
                duration_ms=self._elapsed_ms(started_at),
            )
        except TimeoutError:
            return self._failure(
                started_at,
                code="timeout",
                message=f"Tool timed out after {tool.timeout_seconds:g} seconds",
            )
        except Exception as error:  # noqa: BLE001 - third-party tool boundary
            return self._failure(
                started_at,
                code="execution_failed",
                message=str(error),
            )

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 3)

    def _failure(
        self,
        started_at: float,
        *,
        code: str,
        message: str,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            ok=False,
            error=ToolError(code=code, message=message),  # type: ignore[arg-type]
            duration_ms=self._elapsed_ms(started_at),
        )
