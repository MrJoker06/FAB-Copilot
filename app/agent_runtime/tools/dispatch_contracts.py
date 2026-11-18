"""Small, dependency-free contracts for the isolated tool dispatcher."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    ToolErrorKind,
    ToolExecutionLimits,
    ToolExecutionState,
    ToolResult,
    ToolScope,
    make_tool_error,
    tool_error_details,
)


class ToolInputError(ValueError):
    """A binding explicitly rejected a parsed input as user-facing validation."""


class ToolDataSourceError(RuntimeError):
    """A trusted handler reports a source failure without leaking its details."""


class ToolSourceTimeout(ToolDataSourceError):
    """A source timed out after execution started."""


def exception_tool_error(exc: Exception, *, invalid_arguments: bool = False):
    """Classify legacy handler failures without putting exception text in replies."""
    if invalid_arguments or isinstance(exc, ToolInputError):
        return make_tool_error("INVALID_ARGUMENTS")
    if isinstance(exc, PermissionError):
        return make_tool_error("TOOL_DENIED")
    if isinstance(exc, (ToolSourceTimeout, TimeoutError)):
        return make_tool_error("SOURCE_TIMEOUT")
    if isinstance(exc, ToolDataSourceError):
        return make_tool_error("DATA_SOURCE_FAILED")
    return make_tool_error("TOOL_FAILED")


def exception_tool_failure(exc: Exception, *, invalid_arguments: bool = False):
    error = exception_tool_error(exc, invalid_arguments=invalid_arguments)
    state = ToolExecutionState.COMPLETED
    if error.kind in {ToolErrorKind.INTERNAL, ToolErrorKind.TIMEOUT}:
        state = ToolExecutionState.UNKNOWN
    elif invalid_arguments:
        state = ToolExecutionState.NOT_STARTED
    return tool_error_details(error, state)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    code: str | None = None
    public_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise TypeError("allowed must be a bool")
        if self.allowed and (self.code is not None or self.public_message is not None):
            raise ValueError("allowed policy decisions have no error")
        if not self.allowed and (
            not isinstance(self.code, str)
            or not self.code
            or not isinstance(self.public_message, str)
            or not self.public_message
        ):
            raise ValueError("denied policy decisions require code and message")


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed: bool
    code: str | None = None
    public_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise TypeError("allowed must be a bool")
        if self.allowed and (self.code is not None or self.public_message is not None):
            raise ValueError("allowed budget decisions have no error")
        if not self.allowed and (
            not isinstance(self.code, str)
            or not self.code
            or not isinstance(self.public_message, str)
            or not self.public_message
        ):
            raise ValueError("blocked budget decisions require code and message")


class ToolPolicy(Protocol):
    def authorize(
        self, principal: object, name: str, scope: ToolScope
    ) -> PolicyDecision: ...


class ToolResultPolicy(Protocol):
    """Server-owned post-processing of an already validated tool result."""

    def finalize(
        self,
        result: ToolResult[object],
        arguments: Mapping[str, object],
        limits: ToolExecutionLimits,
    ) -> ToolResult[object]: ...


class ToolBudget(Protocol):
    def claim(
        self, name: str, decoded_arguments: Mapping[str, object]
    ) -> BudgetDecision: ...

    def record_result(self, name: str, data: object, success: bool) -> object: ...
