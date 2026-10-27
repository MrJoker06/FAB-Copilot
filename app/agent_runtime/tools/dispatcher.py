"""Isolated async dispatcher for explicitly authorized typed and legacy tools."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import threading
import time
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .contracts import (
    ToolError,
    ToolErrorKind,
    ToolExecutionContext,
    ToolExecutionState,
    ToolResult,
    ToolScope,
    ToolStatus,
)
from .definition import ToolBinding, ToolPreparation
from .dispatch_contracts import (
    BudgetDecision,
    PolicyDecision,
    ToolDataSourceError,
    ToolInputError,
    ToolResultPolicy,
    ToolSourceTimeout,
)
from .tool_registry import LegacyBindingAdapter

_MAX_ARGUMENT_BYTES = 65_536
_MAX_NAME_LENGTH = 128


class ToolDispatcher:
    def __init__(
        self,
        *,
        run_id: str,
        registry: object,
        policy: object,
        budget: object,
        allowed_tools: frozenset[str],
        legacy_tools: frozenset[str] = frozenset(),
        result_policy: ToolResultPolicy | None = None,
        clock: object = time.monotonic,
        poll_seconds: float = 0.01,
    ) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be non-empty")
        if (
            not isinstance(allowed_tools, frozenset)
            or "*" in allowed_tools
            or any(not self._valid_name(item) for item in allowed_tools)
        ):
            raise ValueError("allowed_tools must be an explicit frozenset")
        if (
            not isinstance(legacy_tools, frozenset)
            or not legacy_tools <= allowed_tools
            or any(not self._valid_name(item) for item in legacy_tools)
        ):
            raise ValueError("legacy_tools must be an allowed frozenset")
        if (
            not callable(clock)
            or not isinstance(poll_seconds, float)
            or poll_seconds <= 0
            or not math.isfinite(poll_seconds)
        ):
            raise ValueError("clock and positive poll_seconds are required")
        if result_policy is not None:
            finalize = getattr(result_policy, "finalize", None)
            if (
                not callable(finalize)
                or inspect.iscoroutinefunction(finalize)
                or inspect.iscoroutinefunction(type(finalize).__call__)
            ):
                raise ValueError(
                    "result_policy must provide a synchronous finalize method"
                )
        self.run_id, self.registry, self.policy, self.budget = (
            run_id,
            registry,
            policy,
            budget,
        )
        self.allowed_tools, self.legacy_tools = allowed_tools, legacy_tools
        self.clock, self.poll_seconds = clock, min(poll_seconds, 0.01)
        self.result_policy = result_policy

    @staticmethod
    def _error(code: str, message: str, kind: ToolErrorKind) -> ToolError:
        return ToolError(code, message, kind)

    def _result(
        self,
        context: ToolExecutionContext[Any],
        name: str,
        status: ToolStatus,
        state: ToolExecutionState,
        code: str,
        message: str,
        kind: ToolErrorKind,
        version: str = "unresolved-v1",
        elapsed: float | None = None,
    ) -> ToolResult[object]:
        return ToolResult(
            context.call_id,
            name,
            version,
            status,
            state,
            error=self._error(code, message, kind),
            elapsed_ms=elapsed,
        )

    @staticmethod
    def _valid_name(name: object) -> bool:
        return (
            isinstance(name, str)
            and bool(name.strip())
            and len(name) <= _MAX_NAME_LENGTH
        )

    @staticmethod
    def _decode(raw: object) -> dict[str, object]:
        if raw is None:
            return {}
        try:
            if isinstance(raw, str):
                if len(raw.encode("utf-8")) > _MAX_ARGUMENT_BYTES:
                    raise ValueError
                value = json.loads(
                    raw, parse_constant=lambda _x: (_ for _ in ()).throw(ValueError())
                )
            elif isinstance(raw, Mapping):
                value = dict(raw)
            else:
                raise TypeError
            if not ToolDispatcher._json_tree(value):
                raise TypeError
            snapshot = json.dumps(
                value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            )
            if len(snapshot.encode("utf-8")) > _MAX_ARGUMENT_BYTES:
                raise TypeError
            decoded = json.loads(snapshot)
            if not isinstance(decoded, dict):
                raise TypeError
            return decoded
        except (RecursionError, TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("invalid arguments") from None

    @staticmethod
    def _json_tree(value: object, depth: int = 0) -> bool:
        if depth > 64:
            return False
        if value is None or isinstance(value, (str, bool, int)):
            return True
        if isinstance(value, float):
            return math.isfinite(value)
        if isinstance(value, list):
            return all(ToolDispatcher._json_tree(item, depth + 1) for item in value)
        if isinstance(value, dict):
            return all(
                isinstance(key, str) and ToolDispatcher._json_tree(item, depth + 1)
                for key, item in value.items()
            )
        return False

    @staticmethod
    def _row_count(data: object) -> int:
        if data is None:
            return 0
        if isinstance(data, (list, tuple)):
            return len(data)
        return 1

    def _legacy_arguments_are_valid(
        self, name: str, arguments: Mapping[str, object]
    ) -> bool:
        """Validate the small JSON-schema subset legacy catalog entries declare."""
        try:
            schema_cell = self.registry.legacy_definition(name).schema
            function = schema_cell.get("function")
            parameters = (
                function.get("parameters") if isinstance(function, Mapping) else None
            )
            if not isinstance(parameters, Mapping):
                return False
            required = parameters.get("required", ())
            properties = parameters.get("properties", {})
            if not isinstance(required, (list, tuple)) or not isinstance(
                properties, Mapping
            ):
                return False
            if any(key not in arguments for key in required if isinstance(key, str)):
                return False
            if parameters.get("additionalProperties") is False and any(
                key not in properties for key in arguments
            ):
                return False
            expected = {
                "string": str,
                "integer": int,
                "number": (int, float),
                "boolean": bool,
                "object": Mapping,
                "array": list,
            }
            for key, value in arguments.items():
                detail = properties.get(key)
                if isinstance(detail, Mapping) and isinstance(detail.get("type"), str):
                    expected_type = expected.get(detail["type"])
                    if expected_type is not None and (
                        not isinstance(value, expected_type)
                        or (
                            detail["type"] in {"integer", "number"}
                            and isinstance(value, bool)
                        )
                    ):
                        return False
            return True
        except Exception:  # noqa: BLE001 - a malformed legacy schema is not executable
            return False

    @staticmethod
    def _cancelled(context: ToolExecutionContext[Any]) -> bool:
        return context.cancellation is not None and context.cancellation.is_cancelled()

    async def dispatch(
        self, name: str, raw_arguments: object, context: ToolExecutionContext[Any]
    ) -> ToolResult[object]:
        started_at = float(self.clock())
        if context.run_id != self.run_id:
            return self._result(
                context,
                name if self._valid_name(name) else "unknown",
                ToolStatus.FAILED,
                ToolExecutionState.NOT_STARTED,
                "RUN_ID_MISMATCH",
                "The tool call does not belong to this run.",
                ToolErrorKind.INTERNAL,
            )
        public_name = name if self._valid_name(name) else "unknown"
        if not self._valid_name(name):
            return self._result(
                context,
                public_name,
                ToolStatus.FAILED,
                ToolExecutionState.NOT_STARTED,
                "UNKNOWN_TOOL",
                "The requested tool is unavailable.",
                ToolErrorKind.INTERNAL,
            )
        try:
            arguments = self._decode(raw_arguments)
        except ValueError:
            return self._result(
                context,
                name,
                ToolStatus.INVALID_ARGUMENTS,
                ToolExecutionState.NOT_STARTED,
                "INVALID_ARGUMENTS",
                "Tool arguments must be a JSON object.",
                ToolErrorKind.PARSING,
            )
        if name not in self.allowed_tools:
            return self._result(
                context,
                name,
                ToolStatus.DENIED,
                ToolExecutionState.NOT_STARTED,
                "TOOL_DENIED",
                "This tool is not authorized.",
                ToolErrorKind.AUTHORIZATION,
            )
        try:
            binding = self.registry.resolve(name)
        except Exception:  # noqa: BLE001 - registry failures are not public details
            return self._result(
                context,
                name,
                ToolStatus.FAILED,
                ToolExecutionState.NOT_STARTED,
                "TOOL_UNAVAILABLE",
                "The requested tool is unavailable.",
                ToolErrorKind.INTERNAL,
            )

        is_legacy = isinstance(binding, LegacyBindingAdapter)
        if is_legacy and name not in self.legacy_tools:
            return self._result(
                context,
                name,
                ToolStatus.DENIED,
                ToolExecutionState.NOT_STARTED,
                "LEGACY_DENIED",
                "This tool is not authorized.",
                ToolErrorKind.AUTHORIZATION,
            )
        if is_legacy and not self._legacy_arguments_are_valid(name, arguments):
            return self._result(
                context,
                name,
                ToolStatus.INVALID_ARGUMENTS,
                ToolExecutionState.NOT_STARTED,
                "INVALID_ARGUMENTS",
                "Tool arguments are invalid.",
                ToolErrorKind.VALIDATION,
                "legacy-v1",
            )
        if not is_legacy and not isinstance(binding, ToolBinding):
            return self._result(
                context,
                name,
                ToolStatus.FAILED,
                ToolExecutionState.NOT_STARTED,
                "TOOL_UNAVAILABLE",
                "The requested tool is unavailable.",
                ToolErrorKind.INTERNAL,
            )
        if not is_legacy and binding.definition.name != name:
            return self._result(
                context,
                name,
                ToolStatus.FAILED,
                ToolExecutionState.NOT_STARTED,
                "TOOL_CONFIGURATION",
                "The tool could not be prepared.",
                ToolErrorKind.INTERNAL,
                binding.definition.version,
            )
        if not is_legacy and not binding.definition.read_only:
            return self._result(
                context,
                name,
                ToolStatus.DENIED,
                ToolExecutionState.NOT_STARTED,
                "READ_ONLY_REQUIRED",
                "This tool is not authorized.",
                ToolErrorKind.AUTHORIZATION,
                binding.definition.version,
            )

        version = "legacy-v1" if is_legacy else binding.definition.version
        scope = ToolScope(context.principal.tenant_id)
        prepared: object = arguments
        narrow_context: ToolExecutionContext[Any] = context
        if not is_legacy:
            try:
                parsed = binding.definition.parse(arguments)
            except ValueError:
                return self._result(
                    context,
                    name,
                    ToolStatus.INVALID_ARGUMENTS,
                    ToolExecutionState.NOT_STARTED,
                    "INVALID_ARGUMENTS",
                    "Tool arguments are invalid.",
                    ToolErrorKind.VALIDATION,
                    version,
                )
            except Exception:  # noqa: BLE001 - invalid binding configuration
                return self._result(
                    context,
                    name,
                    ToolStatus.FAILED,
                    ToolExecutionState.NOT_STARTED,
                    "TOOL_CONFIGURATION",
                    "The tool could not be prepared.",
                    ToolErrorKind.INTERNAL,
                    version,
                )
            if not isinstance(parsed, binding.definition.input_model):
                return self._result(
                    context,
                    name,
                    ToolStatus.FAILED,
                    ToolExecutionState.NOT_STARTED,
                    "TOOL_CONFIGURATION",
                    "The tool could not be prepared.",
                    ToolErrorKind.INTERNAL,
                    version,
                )
            narrow_context = replace(context, dependencies=binding.dependencies)
            if binding.prepare is not None:
                try:
                    preparation = binding.prepare(parsed, narrow_context)
                except ToolInputError:
                    return self._result(
                        context,
                        name,
                        ToolStatus.INVALID_ARGUMENTS,
                        ToolExecutionState.NOT_STARTED,
                        "INVALID_ARGUMENTS",
                        "Tool arguments are invalid.",
                        ToolErrorKind.VALIDATION,
                        version,
                    )
                except Exception:  # noqa: BLE001 - invalid binding configuration
                    return self._result(
                        context,
                        name,
                        ToolStatus.FAILED,
                        ToolExecutionState.NOT_STARTED,
                        "TOOL_PREPARATION_FAILED",
                        "The tool could not be prepared.",
                        ToolErrorKind.INTERNAL,
                        version,
                    )
                if (
                    not isinstance(preparation, ToolPreparation)
                    or not isinstance(
                        preparation.input_value, binding.definition.input_model
                    )
                    or preparation.scope.tenant_id != context.principal.tenant_id
                ):
                    return self._result(
                        context,
                        name,
                        ToolStatus.FAILED,
                        ToolExecutionState.NOT_STARTED,
                        "TOOL_CONFIGURATION",
                        "The tool could not be prepared.",
                        ToolErrorKind.INTERNAL,
                        version,
                    )
                prepared, scope = preparation.input_value, preparation.scope
            else:
                prepared = parsed
            if inspect.iscoroutinefunction(
                binding.handler
            ) or inspect.iscoroutinefunction(
                getattr(binding.handler, "__call__", None)  # noqa: B004
            ):
                return self._result(
                    context,
                    name,
                    ToolStatus.FAILED,
                    ToolExecutionState.NOT_STARTED,
                    "TOOL_CONFIGURATION",
                    "The tool could not be prepared.",
                    ToolErrorKind.INTERNAL,
                    version,
                )

        try:
            decision = self.policy.authorize(context.principal, name, scope)
        except Exception:  # noqa: BLE001 - policy details are not public
            return self._result(
                context,
                name,
                ToolStatus.FAILED,
                ToolExecutionState.NOT_STARTED,
                "POLICY_FAILED",
                "The tool could not be authorized.",
                ToolErrorKind.INTERNAL,
                version,
            )
        if not isinstance(decision, PolicyDecision):
            return self._result(
                context,
                name,
                ToolStatus.FAILED,
                ToolExecutionState.NOT_STARTED,
                "POLICY_FAILED",
                "The tool could not be authorized.",
                ToolErrorKind.INTERNAL,
                version,
            )
        if not decision.allowed:
            return self._result(
                context,
                name,
                ToolStatus.DENIED,
                ToolExecutionState.NOT_STARTED,
                "POLICY_DENIED",
                "This tool is not authorized.",
                ToolErrorKind.AUTHORIZATION,
                version,
            )
        if self._cancelled(context):
            return self._result(
                context,
                name,
                ToolStatus.CANCELLED,
                ToolExecutionState.NOT_STARTED,
                "CANCELLED",
                "The tool call was cancelled.",
                ToolErrorKind.CANCELLATION,
                version,
            )
        deadline = context.limits.deadline_monotonic
        if deadline is not None and float(self.clock()) >= deadline:
            return self._result(
                context,
                name,
                ToolStatus.TIMED_OUT,
                ToolExecutionState.NOT_STARTED,
                "DEADLINE_EXCEEDED",
                "The tool deadline was exceeded.",
                ToolErrorKind.TIMEOUT,
                version,
            )
        if context.limits.remaining_calls == 0:
            return self._result(
                context,
                name,
                ToolStatus.BLOCKED,
                ToolExecutionState.NOT_STARTED,
                "BUDGET_EXHAUSTED",
                "The tool budget is exhausted.",
                ToolErrorKind.BUDGET,
                version,
            )
        try:
            claim = self.budget.claim(name, arguments)
        except Exception:  # noqa: BLE001 - budget details are not public
            return self._result(
                context,
                name,
                ToolStatus.FAILED,
                ToolExecutionState.NOT_STARTED,
                "BUDGET_FAILED",
                "The tool budget could not be checked.",
                ToolErrorKind.INTERNAL,
                version,
            )
        if not isinstance(claim, BudgetDecision):
            return self._result(
                context,
                name,
                ToolStatus.FAILED,
                ToolExecutionState.NOT_STARTED,
                "BUDGET_FAILED",
                "The tool budget could not be checked.",
                ToolErrorKind.INTERNAL,
                version,
            )
        if not claim.allowed:
            return self._result(
                context,
                name,
                ToolStatus.BLOCKED,
                ToolExecutionState.NOT_STARTED,
                "BUDGET_BLOCKED",
                "The tool budget blocked this call.",
                ToolErrorKind.BUDGET,
                version,
            )

        token, lock = {"stopped": False, "started": False}, threading.Lock()

        def invoke() -> object:
            with lock:
                if token["stopped"]:
                    return _NOT_STARTED
                token["started"] = True
            if is_legacy:
                return binding.invoke(arguments)
            return binding.handler(prepared, narrow_context)

        task = asyncio.create_task(asyncio.to_thread(invoke))

        def consume_late(done: asyncio.Task[object]) -> None:
            try:
                done.exception()
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                return

        claimed = True
        try:
            while not task.done():
                if self._cancelled(context):
                    with lock:
                        token["stopped"] = True
                        state = (
                            ToolExecutionState.UNKNOWN
                            if token["started"]
                            else ToolExecutionState.NOT_STARTED
                        )
                    task.add_done_callback(consume_late)
                    result = self._result(
                        context,
                        name,
                        ToolStatus.CANCELLED,
                        state,
                        "CANCELLED",
                        "The tool call was cancelled.",
                        ToolErrorKind.CANCELLATION,
                        version,
                        self._elapsed(started_at),
                    )
                    self._record(name, None, False)
                    return result
                if deadline is not None and float(self.clock()) >= deadline:
                    with lock:
                        token["stopped"] = True
                        state = (
                            ToolExecutionState.UNKNOWN
                            if token["started"]
                            else ToolExecutionState.NOT_STARTED
                        )
                    task.add_done_callback(consume_late)
                    result = self._result(
                        context,
                        name,
                        ToolStatus.TIMED_OUT,
                        state,
                        "DEADLINE_EXCEEDED",
                        "The tool deadline was exceeded.",
                        ToolErrorKind.TIMEOUT,
                        version,
                        self._elapsed(started_at),
                    )
                    self._record(name, None, False)
                    return result
                await asyncio.wait({task}, timeout=self.poll_seconds)
            value = task.result()
        except asyncio.CancelledError:
            with lock:
                token["stopped"] = True
            task.add_done_callback(consume_late)
            if claimed:
                self._record(name, None, False)
            raise
        except (ToolSourceTimeout, TimeoutError):
            return self._finish_error(
                context,
                name,
                version,
                started_at,
                ToolStatus.TIMED_OUT,
                ToolErrorKind.TIMEOUT,
                "SOURCE_TIMEOUT",
                "The tool timed out.",
                ToolExecutionState.UNKNOWN,
            )
        except ToolDataSourceError:
            return self._finish_error(
                context,
                name,
                version,
                started_at,
                ToolStatus.FAILED,
                ToolErrorKind.DATA_SOURCE,
                "DATA_SOURCE_FAILED",
                "The tool data source failed.",
            )
        except Exception:  # noqa: BLE001 - handlers must not leak exception details
            return self._finish_error(
                context,
                name,
                version,
                started_at,
                ToolStatus.FAILED,
                ToolErrorKind.INTERNAL,
                "TOOL_FAILED",
                "The tool could not complete.",
            )
        if value is _NOT_STARTED:
            return self._finish_error(
                context,
                name,
                version,
                started_at,
                ToolStatus.CANCELLED,
                ToolErrorKind.CANCELLATION,
                "CANCELLED",
                "The tool call was cancelled.",
                ToolExecutionState.NOT_STARTED,
            )
        if inspect.isawaitable(value):
            close = getattr(value, "close", None)
            if callable(close):
                close()
            return self._finish_error(
                context,
                name,
                version,
                started_at,
                ToolStatus.FAILED,
                ToolErrorKind.INTERNAL,
                "INVALID_RESULT",
                "The tool returned an invalid result.",
            )
        if is_legacy:
            result = ToolResult(
                context.call_id,
                name,
                version,
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                data=value,
                row_count=self._row_count(value),
                elapsed_ms=self._elapsed(started_at),
            )
        elif not isinstance(value, ToolResult):
            return self._finish_error(
                context,
                name,
                version,
                started_at,
                ToolStatus.FAILED,
                ToolErrorKind.INTERNAL,
                "INVALID_RESULT",
                "The tool returned an invalid result.",
            )
        else:
            result = value
        # Completion is another cancellation/deadline boundary: never adopt a late result.
        if self._cancelled(context):
            return self._finish_error(
                context,
                name,
                version,
                started_at,
                ToolStatus.CANCELLED,
                ToolErrorKind.CANCELLATION,
                "CANCELLED",
                "The tool call was cancelled.",
                ToolExecutionState.UNKNOWN,
            )
        if deadline is not None and float(self.clock()) >= deadline:
            return self._finish_error(
                context,
                name,
                version,
                started_at,
                ToolStatus.TIMED_OUT,
                ToolErrorKind.TIMEOUT,
                "DEADLINE_EXCEEDED",
                "The tool deadline was exceeded.",
                ToolExecutionState.UNKNOWN,
            )
        valid = self._validate_result(
            result,
            context,
            name,
            version,
            scope,
            started_at,
            None if is_legacy else binding,
            enforce_limit=self.result_policy is None,
        )
        if valid.status is ToolStatus.SUCCEEDED and self.result_policy is not None:
            raw = valid
            try:
                projected = self.result_policy.finalize(raw, arguments, context.limits)
            except asyncio.CancelledError:
                self._record(name, None, False)
                raise
            except Exception:  # noqa: BLE001 - policy details are not public
                return self._finish_error(
                    context,
                    name,
                    version,
                    started_at,
                    ToolStatus.FAILED,
                    ToolErrorKind.INTERNAL,
                    "RESULT_POLICY_FAILED",
                    "The tool result could not be finalized.",
                )
            if inspect.isawaitable(projected):
                close = getattr(projected, "close", None)
                if callable(close):
                    close()
                return self._finish_error(
                    context,
                    name,
                    version,
                    started_at,
                    ToolStatus.FAILED,
                    ToolErrorKind.INTERNAL,
                    "INVALID_RESULT",
                    "The tool returned an invalid result.",
                )
            if (
                not isinstance(projected, ToolResult)
                or projected.status is not ToolStatus.SUCCEEDED
                or projected.execution_state is not ToolExecutionState.COMPLETED
                or projected.call_id != raw.call_id
                or projected.tool_name != raw.tool_name
                or projected.tool_version != raw.tool_version
                or projected.sources != raw.sources
            ):
                return self._finish_error(
                    context,
                    name,
                    version,
                    started_at,
                    ToolStatus.FAILED,
                    ToolErrorKind.INTERNAL,
                    "INVALID_RESULT",
                    "The tool returned an invalid result.",
                )
            valid = self._validate_result(
                projected,
                context,
                name,
                version,
                scope,
                started_at,
                None if is_legacy else binding,
            )
        if valid.status is ToolStatus.SUCCEEDED and self._cancelled(context):
            return self._finish_error(
                context,
                name,
                version,
                started_at,
                ToolStatus.CANCELLED,
                ToolErrorKind.CANCELLATION,
                "CANCELLED",
                "The tool call was cancelled.",
                ToolExecutionState.UNKNOWN,
            )
        if (
            valid.status is ToolStatus.SUCCEEDED
            and deadline is not None
            and float(self.clock()) >= deadline
        ):
            return self._finish_error(
                context,
                name,
                version,
                started_at,
                ToolStatus.TIMED_OUT,
                ToolErrorKind.TIMEOUT,
                "DEADLINE_EXCEEDED",
                "The tool deadline was exceeded.",
                ToolExecutionState.UNKNOWN,
            )
        if (
            not self._record(
                name,
                valid.data if valid.status is ToolStatus.SUCCEEDED else None,
                valid.status is ToolStatus.SUCCEEDED,
            )
            and valid.status is ToolStatus.SUCCEEDED
        ):
            return self._result(
                context,
                name,
                ToolStatus.FAILED,
                ToolExecutionState.COMPLETED,
                "ACCOUNTING_FAILED",
                "The tool result could not be recorded.",
                ToolErrorKind.INTERNAL,
                version,
                self._elapsed(started_at),
            )
        return valid

    def _elapsed(self, started: float) -> float:
        try:
            elapsed = (float(self.clock()) - started) * 1000.0
        except (TypeError, ValueError):
            return 0.0
        return elapsed if math.isfinite(elapsed) and elapsed >= 0 else 0.0

    def _record(self, name: str, data: object, success: bool) -> bool:
        try:
            self.budget.record_result(name, data, success)
        except Exception:  # noqa: BLE001 - accounting cannot leak or retry
            return False
        return True

    def _finish_error(
        self,
        context: ToolExecutionContext[Any],
        name: str,
        version: str,
        started: float,
        status: ToolStatus,
        kind: ToolErrorKind,
        code: str,
        message: str,
        state: ToolExecutionState = ToolExecutionState.COMPLETED,
    ) -> ToolResult[object]:
        result = self._result(
            context,
            name,
            status,
            state,
            code,
            message,
            kind,
            version,
            self._elapsed(started),
        )
        try:
            self.budget.record_result(name, None, False)
        except Exception:  # noqa: BLE001 - accounting cannot leak or retry
            return result
        return result

    def _validate_result(
        self,
        result: ToolResult[object],
        context: ToolExecutionContext[Any],
        name: str,
        version: str,
        scope: ToolScope,
        started: float,
        binding: ToolBinding[Any, Any, Any] | None,
        *,
        enforce_limit: bool = True,
    ) -> ToolResult[object]:
        def bad() -> ToolResult[object]:
            return self._result(
                context,
                name,
                ToolStatus.FAILED,
                ToolExecutionState.COMPLETED,
                "INVALID_RESULT",
                "The tool returned an invalid result.",
                ToolErrorKind.INTERNAL,
                version,
                self._elapsed(started),
            )

        if (
            result.call_id != context.call_id
            or result.tool_name != name
            or result.tool_version != version
        ):
            return bad()
        if result.status is not ToolStatus.SUCCEEDED:
            return replace(result, elapsed_ms=self._elapsed(started))
        try:
            # Validation is intentionally only a check: retain the handler payload identity.
            if isinstance(binding, ToolBinding):
                binding.definition.output_validator(result.data)
        except Exception:  # noqa: BLE001 - output validation failure is internal
            return bad()
        if any(source.scope != scope for source in result.sources) or (
            scope != ToolScope(scope.tenant_id) and not result.sources
        ):
            return bad()
        rows = self._row_count(result.data)
        if result.row_count is not None and result.row_count != rows:
            return bad()
        if enforce_limit and (
            context.limits.max_result_rows is not None
            and rows > context.limits.max_result_rows
        ):
            return bad()
        return replace(result, row_count=rows, elapsed_ms=self._elapsed(started))


_NOT_STARTED = object()

__all__ = ["ToolDispatcher"]
