"""Dependency-free contracts for future typed Agent tool execution.

These envelopes are intentionally additive. They do not adapt or change the
legacy tool registry, its SQL compatibility entry point, or execution policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from math import isfinite
from typing import Generic, Protocol, TypeVar

TOOL_CONTRACT_VERSION = "1.0.0"

DepsT = TypeVar("DepsT")
DataT = TypeVar("DataT")


class ToolPrincipal(Protocol):
    """Trusted server-supplied identity claims; this protocol authenticates nobody."""

    @property
    def tenant_id(self) -> str: ...

    @property
    def user_id(self) -> str: ...

    @property
    def roles(self) -> tuple[str, ...]: ...


class CancellationSignal(Protocol):
    """A cooperative cancellation signal owned and interpreted by the runtime."""

    def is_cancelled(self) -> bool: ...


def _non_empty_string(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _non_negative_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer or None")


def _finite_non_negative_float(value: object, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, float)
        or not isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be a finite non-negative float or None")


def _optional_date(value: object, name: str) -> None:
    if value is not None and (
        isinstance(value, datetime) or not isinstance(value, date)
    ):
        raise ValueError(f"{name} must be a date or None")


def _string_tuple(value: object, name: str) -> None:
    if not isinstance(value, tuple) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{name} must be a tuple of strings")


@dataclass(frozen=True, slots=True)
class ToolExecutionLimits:
    """A runtime-owned budget snapshot; this object neither reads clocks nor mutates budgets."""

    remaining_calls: int | None = None
    max_result_rows: int | None = None
    deadline_monotonic: float | None = None

    def __post_init__(self) -> None:
        if self.remaining_calls is not None:
            _non_negative_int(self.remaining_calls, "remaining_calls")
        if self.max_result_rows is not None:
            _non_negative_int(self.max_result_rows, "max_result_rows")
        if self.deadline_monotonic is not None:
            _finite_non_negative_float(self.deadline_monotonic, "deadline_monotonic")


@dataclass(frozen=True, slots=True)
class ToolExecutionContext(Generic[DepsT]):
    """Per-call trusted context with a typed, tool-specific dependency aggregate."""

    principal: ToolPrincipal
    run_id: str
    call_id: str
    dependencies: DepsT
    step_id: str | None = None
    limits: ToolExecutionLimits = field(default_factory=ToolExecutionLimits)
    cancellation: CancellationSignal | None = None

    def __post_init__(self) -> None:
        _non_empty_string(self.run_id, "run_id")
        _non_empty_string(self.call_id, "call_id")
        if self.step_id is not None:
            _non_empty_string(self.step_id, "step_id")
        if not isinstance(self.limits, ToolExecutionLimits):
            raise ValueError("limits must be a ToolExecutionLimits")  # noqa: TRY004
        for attribute in ("tenant_id", "user_id", "roles"):
            if not hasattr(self.principal, attribute):
                raise ValueError("principal must provide tenant_id, user_id, and roles")
        _non_empty_string(self.principal.tenant_id, "principal.tenant_id")
        _non_empty_string(self.principal.user_id, "principal.user_id")
        _string_tuple(self.principal.roles, "principal.roles")
        if self.cancellation is not None and not callable(
            getattr(self.cancellation, "is_cancelled", None)
        ):
            raise ValueError("cancellation must provide is_cancelled()")


class ToolStatus(str, Enum):
    SUCCEEDED = "succeeded"
    INVALID_ARGUMENTS = "invalid_arguments"
    DENIED = "denied"
    BLOCKED = "blocked"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class ToolErrorKind(str, Enum):
    PARSING = "parsing"
    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    BUDGET = "budget"
    DATA_SOURCE = "data_source"
    INTERNAL = "internal"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"


class ToolExecutionState(str, Enum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    CANCELLED_CONFIRMED = "cancelled_confirmed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ToolError:
    """Caller-sanitized public error information, never a raw exception wrapper."""

    code: str
    public_message: str
    kind: ToolErrorKind
    retryable: bool = False

    def __post_init__(self) -> None:
        _non_empty_string(self.code, "code")
        _non_empty_string(self.public_message, "public_message")
        if not isinstance(self.kind, ToolErrorKind):
            raise ValueError("kind must be a ToolErrorKind")  # noqa: TRY004
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable must be a bool")  # noqa: TRY004


@dataclass(frozen=True, slots=True)
class ToolScope:
    tenant_id: str
    start_date: date | None = None
    end_date: date | None = None
    equipment_ids: tuple[str, ...] = ()
    process_steps: tuple[str, ...] = ()
    lot_ids: tuple[str, ...] = ()
    grain: str | None = None

    def __post_init__(self) -> None:
        _non_empty_string(self.tenant_id, "tenant_id")
        _optional_date(self.start_date, "start_date")
        _optional_date(self.end_date, "end_date")
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be supplied together")
        if self.start_date is not None and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        for name in ("equipment_ids", "process_steps", "lot_ids"):
            _string_tuple(getattr(self, name), name)
        if self.grain is not None:
            _non_empty_string(self.grain, "grain")


class ToolSourceKind(str, Enum):
    FAKE = "fake"
    SQLITE = "sqlite"
    DATABASE = "database"
    REPORT_API = "report_api"
    KNOWLEDGE = "knowledge"


@dataclass(frozen=True, slots=True)
class ToolSource:
    """Safe provenance metadata only; it does not itself enforce row-level ACLs."""

    source_ref: str
    adapter_id: str
    source_kind: ToolSourceKind
    scope: ToolScope

    def __post_init__(self) -> None:
        _non_empty_string(self.source_ref, "source_ref")
        _non_empty_string(self.adapter_id, "adapter_id")
        if not isinstance(self.source_kind, ToolSourceKind):
            raise ValueError("source_kind must be a ToolSourceKind")  # noqa: TRY004
        if not isinstance(self.scope, ToolScope):
            raise ValueError("scope must be a ToolScope")  # noqa: TRY004


_ERROR_KINDS = {
    ToolStatus.INVALID_ARGUMENTS: {ToolErrorKind.PARSING, ToolErrorKind.VALIDATION},
    ToolStatus.DENIED: {ToolErrorKind.AUTHORIZATION},
    ToolStatus.BLOCKED: {ToolErrorKind.BUDGET},
    ToolStatus.FAILED: {ToolErrorKind.DATA_SOURCE, ToolErrorKind.INTERNAL},
    ToolStatus.TIMED_OUT: {ToolErrorKind.TIMEOUT},
    ToolStatus.CANCELLED: {ToolErrorKind.CANCELLATION},
}


@dataclass(frozen=True, slots=True)
class ToolResult(Generic[DataT]):
    call_id: str
    tool_name: str
    tool_version: str
    status: ToolStatus
    execution_state: ToolExecutionState
    data: DataT | None = None
    error: ToolError | None = None
    sources: tuple[ToolSource, ...] = ()
    row_count: int | None = None
    elapsed_ms: float | None = None
    contract_version: str = TOOL_CONTRACT_VERSION

    def __post_init__(self) -> None:
        for name in ("call_id", "tool_name", "tool_version"):
            _non_empty_string(getattr(self, name), name)
        if self.contract_version != TOOL_CONTRACT_VERSION:
            raise ValueError("contract_version must match TOOL_CONTRACT_VERSION")
        if not isinstance(self.status, ToolStatus):
            raise ValueError("status must be a ToolStatus")  # noqa: TRY004
        if not isinstance(self.execution_state, ToolExecutionState):
            raise ValueError("execution_state must be a ToolExecutionState")  # noqa: TRY004
        if self.error is not None and not isinstance(self.error, ToolError):
            raise ValueError("error must be a ToolError or None")
        if not isinstance(self.sources, tuple) or any(
            not isinstance(item, ToolSource) for item in self.sources
        ):
            raise ValueError("sources must be a tuple of ToolSource")
        if self.row_count is not None:
            _non_negative_int(self.row_count, "row_count")
        if self.elapsed_ms is not None:
            _finite_non_negative_float(self.elapsed_ms, "elapsed_ms")

        if self.status is ToolStatus.SUCCEEDED:
            if (
                self.execution_state is not ToolExecutionState.COMPLETED
                or self.error is not None
            ):
                raise ValueError(
                    "succeeded results require completed state and no error"
                )
            return
        if self.data is not None:
            raise ValueError("non-succeeded results cannot carry data")
        if self.error is None:
            raise ValueError("non-succeeded results require an error")
        if self.status in {
            ToolStatus.INVALID_ARGUMENTS,
            ToolStatus.DENIED,
            ToolStatus.BLOCKED,
        }:
            if self.execution_state is not ToolExecutionState.NOT_STARTED:
                raise ValueError("pre-execution result must have not_started state")
        elif self.status is ToolStatus.FAILED:
            if self.execution_state not in {
                ToolExecutionState.NOT_STARTED,
                ToolExecutionState.COMPLETED,
                ToolExecutionState.UNKNOWN,
            }:
                raise ValueError(
                    "failed result must have not_started, completed, or unknown state"
                )
        elif self.status in {
            ToolStatus.TIMED_OUT,
            ToolStatus.CANCELLED,
        } and self.execution_state not in {
            ToolExecutionState.NOT_STARTED,
            ToolExecutionState.UNKNOWN,
            ToolExecutionState.CANCELLED_CONFIRMED,
        }:
            raise ValueError(
                "timed_out or cancelled result has an invalid execution state"
            )
        if self.error.kind not in _ERROR_KINDS[self.status]:
            raise ValueError("error kind does not match result status")
