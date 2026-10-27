"""Small, dependency-free contracts for the typed runtime-port pilot."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

from ..tools.contracts import (
    CancellationSignal,
    ToolExecutionContext,
    ToolExecutionLimits,
    ToolExecutionState,
    ToolPrincipal,
    ToolStatus,
)

_MAX_TOOLS_JSON_BYTES = 1_048_576
_MAX_TOOL_NAME_LENGTH = 128
_MODEL_ROLES = frozenset({"system", "user", "assistant", "tool"})
_EVENT_KINDS = frozenset({"model_response", "tool_result"})

ValueT = TypeVar("ValueT")


def _non_empty_string(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _non_negative_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _finite_json_tree(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_finite_json_tree(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _finite_json_tree(item)
            for key, item in value.items()
        )
    return False


def _validate_tools_json(value: object) -> None:
    if not isinstance(value, str):
        raise ValueError("tools_json must be a string")  # noqa: TRY004
    try:
        if len(value.encode("utf-8")) > _MAX_TOOLS_JSON_BYTES:
            raise ValueError
        parsed = json.loads(
            value,
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
        )
        if (
            not isinstance(parsed, list)
            or any(not isinstance(item, dict) for item in parsed)
            or not _finite_json_tree(parsed)
        ):
            raise ValueError
    except (RecursionError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("tools_json must be a finite JSON array of objects") from None


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """Trusted runtime values retained across a model or tool stage."""

    principal: ToolPrincipal
    run_id: str
    limits: ToolExecutionLimits = field(default_factory=ToolExecutionLimits)
    cancellation: CancellationSignal | None = None

    def __post_init__(self) -> None:
        ToolExecutionContext(
            principal=self.principal,
            run_id=self.run_id,
            call_id="runtime-context-validation",
            dependencies=None,
            limits=self.limits,
            cancellation=self.cancellation,
        )

    def for_tool_call(
        self, call_id: str, step_id: str | None = None
    ) -> ToolExecutionContext[None]:
        return ToolExecutionContext(
            principal=self.principal,
            run_id=self.run_id,
            call_id=call_id,
            dependencies=None,
            step_id=step_id,
            limits=self.limits,
            cancellation=self.cancellation,
        )


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    """A provider-associated tool call whose arguments stay unparsed."""

    call_id: str
    name: str
    arguments: str

    def __post_init__(self) -> None:
        _non_empty_string(self.call_id, "call_id")
        _non_empty_string(self.name, "name")
        if len(self.name) > _MAX_TOOL_NAME_LENGTH:
            raise ValueError("name must not exceed 128 characters")
        if not isinstance(self.arguments, str):
            raise ValueError("arguments must be a string")  # noqa: TRY004


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ModelToolCall, ...] = ()
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or self.role not in _MODEL_ROLES:
            raise ValueError("role must be a supported model role")
        if not isinstance(self.content, str):
            raise ValueError("content must be a string")  # noqa: TRY004
        if not isinstance(self.tool_calls, tuple) or any(
            not isinstance(call, ModelToolCall) for call in self.tool_calls
        ):
            raise ValueError("tool_calls must be a tuple of ModelToolCall")
        if self.tool_call_id is not None:
            _non_empty_string(self.tool_call_id, "tool_call_id")
        if self.role == "tool":
            if self.tool_call_id is None:
                raise ValueError("tool messages require tool_call_id")
        elif self.tool_call_id is not None:
            raise ValueError("only tool messages may have tool_call_id")
        if self.tool_calls and self.role != "assistant":
            raise ValueError("only assistant messages may have tool_calls")


@dataclass(frozen=True, slots=True)
class ModelUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        _non_negative_int(self.prompt_tokens, "prompt_tokens")
        _non_negative_int(self.completion_tokens, "completion_tokens")
        _non_negative_int(self.total_tokens, "total_tokens")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    call_id: str
    messages: tuple[ModelMessage, ...]
    tools_json: str = "[]"

    def __post_init__(self) -> None:
        _non_empty_string(self.call_id, "call_id")
        if not isinstance(self.messages, tuple) or any(
            not isinstance(message, ModelMessage) for message in self.messages
        ):
            raise ValueError("messages must be a tuple of ModelMessage")
        _validate_tools_json(self.tools_json)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str = ""
    tool_calls: tuple[ModelToolCall, ...] = ()
    usage: ModelUsage = field(default_factory=ModelUsage)
    response_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise ValueError("content must be a string")  # noqa: TRY004
        if not isinstance(self.tool_calls, tuple) or any(
            not isinstance(call, ModelToolCall) for call in self.tool_calls
        ):
            raise ValueError("tool_calls must be a tuple of ModelToolCall")
        if len({call.call_id for call in self.tool_calls}) != len(self.tool_calls):
            raise ValueError("tool_calls must not repeat call_id")
        if not isinstance(self.usage, ModelUsage):
            raise ValueError("usage must be a ModelUsage")  # noqa: TRY004
        if self.response_id is not None:
            _non_empty_string(self.response_id, "response_id")


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """A versioned, payload-free summary of one completed runtime stage."""

    run_id: str
    call_id: str
    kind: Literal["model_response", "tool_result"]
    status: ToolStatus
    tool_name: str | None = None
    row_count: int | None = None
    usage: ModelUsage | None = None
    schema_version: str = "1.0.0"
    execution_state: ToolExecutionState | None = None

    def __post_init__(self) -> None:
        _non_empty_string(self.run_id, "run_id")
        _non_empty_string(self.call_id, "call_id")
        if not isinstance(self.kind, str) or self.kind not in _EVENT_KINDS:
            raise ValueError("kind must be a supported runtime event kind")
        if not isinstance(self.status, ToolStatus):
            raise ValueError("status must be a ToolStatus")  # noqa: TRY004
        if self.row_count is not None:
            _non_negative_int(self.row_count, "row_count")
        if self.schema_version != "1.0.0":
            raise ValueError("schema_version must be 1.0.0")
        if self.kind == "model_response":
            if (
                self.status is not ToolStatus.SUCCEEDED
                or not isinstance(self.usage, ModelUsage)
                or self.tool_name is not None
                or self.row_count is not None
                or self.execution_state is not None
            ):
                raise ValueError(
                    "model_response events require succeeded status and usage"
                )
            return
        if self.usage is not None:
            raise ValueError("tool_result events must not include usage")
        _non_empty_string(self.tool_name, "tool_name")
        if not isinstance(self.execution_state, ToolExecutionState):
            raise ValueError("tool_result events require execution_state")  # noqa: TRY004


@dataclass(frozen=True, slots=True)
class StageResult(Generic[ValueT]):
    value: ValueT
    event: RuntimeEvent

    def __post_init__(self) -> None:
        if not isinstance(self.event, RuntimeEvent):
            raise ValueError("event must be a RuntimeEvent")  # noqa: TRY004


class RuntimeContractError(RuntimeError):
    """Raised when a runtime Port violates its small response contract."""
