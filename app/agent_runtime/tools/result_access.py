"""A per-run auxiliary result reader using the existing Tool/Dispatcher contracts."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Protocol

from ...core.tool_result_units import canonical_json
from ..execution.loop_guard import ToolLoopGuard
from .contracts import (
    ToolErrorKind,
    ToolExecutionState,
    ToolResult,
    ToolStatus,
    make_tool_error,
    tool_error_details,
)
from .definition import ToolBinding, ToolDefinition
from .dispatch_contracts import BudgetDecision, PolicyDecision
from .dispatcher import ToolDispatcher
from .tool_registry import DEFAULT_TOOL_REGISTRY


class ResultReader(Protocol):
    def read(self, **parameters: Any) -> dict: ...


@dataclass(frozen=True)
class ResultReadInput:
    result_ref: str
    cursor: str | None = None
    limit: int = 20

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]):
        if set(arguments) - {"result_ref", "cursor", "limit"}:
            raise ValueError("Unknown result read fields")
        reference, cursor, limit = (
            arguments.get("result_ref"),
            arguments.get("cursor"),
            arguments.get("limit", 20),
        )
        if type(reference) is not str or not reference or len(reference) > 128:
            raise ValueError("Invalid result reference")
        if "cursor" in arguments and (
            type(cursor) is not str or not cursor or len(cursor) > 2048
        ):
            raise ValueError("Invalid result cursor")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid result page limit")
        return cls(reference, cursor, limit)

    @classmethod
    def json_schema(cls):
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "result_ref": {"type": "string", "minLength": 1, "maxLength": 128},
                "cursor": {"type": "string", "minLength": 1, "maxLength": 2048},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                },
            },
            "required": ["result_ref"],
        }


def _validate_output(data):
    if type(data) is not dict or data.get("format") not in {"units", "unit_fragment"}:
        raise ValueError("Invalid result page")
    if type(data.get("has_more")) is not bool or "next_cursor" not in data:
        raise ValueError("Invalid result page")
    if data.get("unit_kind") not in {"records", "paragraphs", "entries", "scalar"}:
        raise ValueError("Invalid result units")
    if type(data.get("total_units")) is not int or data["total_units"] < 0:
        raise ValueError("Invalid result units")
    if data["format"] == "units":
        if (
            type(data.get("units")) is not list
            or type(data.get("start_unit")) is not int
            or data["start_unit"] < 0
        ):
            raise ValueError("Invalid result units")
    elif type(data.get("text")) is not str or any(
        type(data.get(key)) is not int or data[key] < 0
        for key in ("unit_index", "start_char", "end_char", "total_chars")
    ):
        raise ValueError("Invalid result fragment")
    if len(canonical_json(data).encode("utf-8")) > 4096:
        raise ValueError("Result page too large")
    return data


RESULT_READ_DEFINITION = ToolDefinition(
    name="read_tool_result",
    version="1.0.0",
    description="按引用分页读取当前会话已保存的工具结果快照；返回原查询时间和范围，不查询最新业务数据。",
    input_model=ResultReadInput,
    output_validator=_validate_output,
    output_schema={
        "type": "object",
        "properties": {
            "format": {"enum": ["units", "unit_fragment"]},
            "result_ref": {"type": "string"},
            "has_more": {"type": "boolean"},
            "next_cursor": {"type": ["string", "null"]},
            "unit_kind": {"enum": ["records", "paragraphs", "entries", "scalar"]},
            "total_units": {"type": "integer", "minimum": 0},
            "queried_at": {"type": "string"},
            "scope": {"type": "object"},
            "source_ref": {"type": "string"},
        },
        "required": [
            "format",
            "result_ref",
            "has_more",
            "next_cursor",
            "unit_kind",
            "total_units",
        ],
        "oneOf": [
            {
                "properties": {
                    "format": {"const": "units"},
                    "units": {"type": "array"},
                    "start_unit": {"type": "integer", "minimum": 0},
                },
                "required": ["units", "start_unit"],
            },
            {
                "properties": {
                    "format": {"const": "unit_fragment"},
                    "text": {"type": "string"},
                    **{
                        key: {"type": "integer", "minimum": 0}
                        for key in (
                            "unit_index",
                            "start_char",
                            "end_char",
                            "total_chars",
                        )
                    },
                },
                "required": [
                    "text",
                    "unit_index",
                    "start_char",
                    "end_char",
                    "total_chars",
                ],
            },
        ],
    },
)


def result_read_content(result: ToolResult) -> str:
    if result.status is ToolStatus.SUCCEEDED:
        return canonical_json(result.data)
    return canonical_json(
        {
            "ok": False,
            **tool_error_details(result.error, result.execution_state),
        }
    )


@dataclass
class ResultReadAccess:
    reader: ResultReader
    principal: Any
    session_id: str
    run_id: str
    guard: ToolLoopGuard
    authorize: Callable[[], bool]
    enabled: bool = True
    phase: str = "collection"
    deadline: float | None = None
    cancelled: Callable[[], bool] = lambda: False
    reads: int = 0
    response_bytes: int = 0
    _pending: int = 0
    _lock: Any = field(default_factory=threading.Lock, repr=False)
    authorize_snapshot: Callable[[dict, Any], bool] | None = None

    def permitted(self, principal=None) -> bool:
        principal = self.principal if principal is None else principal
        return bool(
            self.enabled
            and self.session_id
            and self.phase == "synthesis"
            and self.deadline is not None
            and time.monotonic() < self.deadline
            and not self.cancelled()
            and principal.tenant_id == self.principal.tenant_id
            and principal.user_id == self.principal.user_id
            and "analyst" in principal.roles
            and self.authorize()
        )

    def claim(self, name, arguments) -> BudgetDecision:
        with self._lock:
            if name != RESULT_READ_DEFINITION.name or not self.permitted():
                return BudgetDecision(False, "RESULT_UNAVAILABLE", "结果当前不可读取。")
            if (
                self.reads >= 4
                or self.response_bytes >= 16384
                or not self.guard.claim_auxiliary_read()
            ):
                return BudgetDecision(
                    False, "RESULT_READ_BUDGET", "结果读取预算已用尽。"
                )
            self.reads += 1
            self._pending += 1
            return BudgetDecision(True)

    def record_result(self, name, data, success):
        # Auxiliary reads never become a new evidence observation/progress item.
        return False

    def charge_rejected_input(self, result) -> BudgetDecision:
        decision = self.claim(RESULT_READ_DEFINITION.name, {})
        if decision.allowed:
            with self._lock:
                self._pending -= 1
                self.response_bytes += len(result_read_content(result).encode("utf-8"))
        return decision

    def policy(self, principal, name, scope):
        allowed = name == RESULT_READ_DEFINITION.name and self.permitted(principal)
        return PolicyDecision(
            allowed,
            None if allowed else "RESULT_UNAVAILABLE",
            None if allowed else "结果当前不可读取。",
        )

    def read(self, value: ResultReadInput, context) -> ToolResult:
        def failure(code, status, kind, state=ToolExecutionState.NOT_STARTED):
            return ToolResult(
                context.call_id,
                RESULT_READ_DEFINITION.name,
                "1.0.0",
                status,
                state,
                error=make_tool_error(code, kind),
            )

        # The Dispatcher owns the claim; each claim can fund only one handler.
        with self._lock:
            if self._pending < 1:
                return failure(
                    "RESULT_UNAVAILABLE",
                    ToolStatus.DENIED,
                    ToolErrorKind.AUTHORIZATION,
                )
            self._pending -= 1
            try:
                if context.run_id != self.run_id or not self.permitted(
                    context.principal
                ):
                    raise ValueError("RESULT_UNAVAILABLE")
                data = self.reader.read(
                    tenant_id=self.principal.tenant_id,
                    owner_id=self.principal.user_id,
                    session_id=self.session_id,
                    result_ref=value.result_ref,
                    cursor=value.cursor,
                    limit=value.limit,
                    max_bytes=min(4096, 16384 - self.response_bytes),
                    permit=lambda: self.permitted(context.principal),
                    **({"authorize_snapshot": self.authorize_snapshot} if self.authorize_snapshot else {}),
                )
                _validate_output(data)
                result = ToolResult(
                    context.call_id,
                    RESULT_READ_DEFINITION.name,
                    "1.0.0",
                    ToolStatus.SUCCEEDED,
                    ToolExecutionState.COMPLETED,
                    data=data,
                )
            except Exception as exc:  # noqa: BLE001 - never expose reader/backend details
                code = getattr(exc, "code", None)
                if code is None and str(exc) == "RESULT_UNAVAILABLE":
                    code = "RESULT_UNAVAILABLE"
                if code == "RESULT_UNAVAILABLE":
                    result = failure(
                        code,
                        ToolStatus.DENIED,
                        ToolErrorKind.AUTHORIZATION,
                    )
                elif code in {"RESULT_CURSOR_INVALID", "RESULT_INVALID"}:
                    result = failure(
                        code,
                        ToolStatus.INVALID_ARGUMENTS,
                        ToolErrorKind.VALIDATION,
                    )
                elif code == "RESULT_RESPONSE_LIMIT":
                    result = failure(
                        code,
                        ToolStatus.BLOCKED,
                        ToolErrorKind.BUDGET,
                    )
                else:
                    result = failure(
                        "RESULT_READ_FAILED",
                        ToolStatus.FAILED,
                        ToolErrorKind.INTERNAL,
                        ToolExecutionState.COMPLETED,
                    )
            self.response_bytes += len(result_read_content(result).encode("utf-8"))
            return result


def result_read_binding(access: ResultReadAccess):
    return ToolBinding(
        RESULT_READ_DEFINITION,
        lambda value, context: access.read(value, context),
        access,
    )


def install_result_reader(registry, access: ResultReadAccess):
    """Add the auxiliary binding to the caller's run registry, never global TOOLS."""
    if registry is DEFAULT_TOOL_REGISTRY:
        raise ValueError("Result reads require a per-run registry")
    registry.register_native(result_read_binding(access))
    return ToolDispatcher(
        run_id=access.run_id,
        registry=registry,
        policy=SimpleNamespace(authorize=access.policy),
        budget=access,
        allowed_tools=frozenset({RESULT_READ_DEFINITION.name}),
    )
