"""Project dispatcher results into the legacy-shaped observation envelope.

This module deliberately contains no evidence validation or business-tool knowledge.
For successful typed calls, source scopes are authoritative.  Legacy calls which
have no source metadata retain their submitted arguments; callers must treat that
as an explicitly less-trusted compatibility path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tools.contracts import ToolResult, ToolStatus


@dataclass(frozen=True, slots=True)
class ToolResultProjection:
    """A serializable projection which remains compatible with EvidenceObservation."""

    observation: dict[str, Any]
    trace: dict[str, Any]
    sources: tuple[dict[str, Any], ...]
    provenance: tuple[dict[str, Any], ...]
    event: dict[str, Any]


def _scope_value(values: list[str]) -> str | list[str] | None:
    distinct = list(dict.fromkeys(values))
    if not distinct:
        return None
    return distinct[0] if len(distinct) == 1 else distinct


def _source_payload(result: ToolResult[object]) -> tuple[dict[str, Any], ...]:
    payload: list[dict[str, Any]] = []
    for source in result.sources:
        scope = source.scope
        payload.append(
            {
                "source_ref": source.source_ref,
                "adapter_id": source.adapter_id,
                "source_kind": source.source_kind.value,
                "scope": {
                    "tenant_id": scope.tenant_id,
                    "start": scope.start_date.isoformat() if scope.start_date else None,
                    "end": scope.end_date.isoformat() if scope.end_date else None,
                    "equipment_ids": list(scope.equipment_ids),
                    "process_steps": list(scope.process_steps),
                    "lot_ids": list(scope.lot_ids),
                    "grain": scope.grain,
                },
            }
        )
    return tuple(payload)


def _trusted_arguments(
    submitted: dict[str, Any], result: ToolResult[object]
) -> dict[str, Any]:
    """Replace standard filters with source scope without inventing a single value."""
    if not result.sources:
        return dict(submitted)
    value = dict(submitted)
    for key in (
        "start",
        "end",
        "process_step",
        "equipment_id",
        "lot_id",
        "process_steps",
        "equipment_ids",
        "lot_ids",
    ):
        value.pop(key, None)
    starts = [
        source.scope.start_date.isoformat()
        for source in result.sources
        if source.scope.start_date
    ]
    ends = [
        source.scope.end_date.isoformat()
        for source in result.sources
        if source.scope.end_date
    ]
    equipment = [
        item for source in result.sources for item in source.scope.equipment_ids
    ]
    processes = [
        item for source in result.sources for item in source.scope.process_steps
    ]
    lots = [item for source in result.sources for item in source.scope.lot_ids]
    for key, values in (
        ("start", starts),
        ("end", ends),
        ("equipment_id", equipment),
        ("process_step", processes),
        ("lot_id", lots),
    ):
        item = _scope_value(values)
        if item is not None:
            value[key] = item
    return value


def project_tool_result(
    result: ToolResult[object],
    *,
    arguments: dict[str, Any] | None = None,
    step_id: str | None = None,
) -> ToolResultProjection:
    """Return sanitized observation, trace, provenance and terminal-event payloads."""
    if not isinstance(result, ToolResult):
        raise TypeError("result must be a ToolResult")
    submitted = dict(arguments or {})
    source_ref = "TOOL:" + (step_id or result.call_id)
    succeeded = result.status is ToolStatus.SUCCEEDED
    blocked = result.status in {ToolStatus.DENIED, ToolStatus.BLOCKED}
    observation_status = "success" if succeeded else "blocked" if blocked else "error"
    error = None if succeeded else result.error.public_message
    observation = {
        "tool": result.tool_name,
        "arguments": _trusted_arguments(submitted, result) if succeeded else {},
        "status": observation_status,
        "result": result.data if succeeded else None,
        "error": error,
        "source_ref": source_ref,
    }
    sources = _source_payload(result)
    trace = {
        "call_id": result.call_id,
        "tool": result.tool_name,
        "tool_version": result.tool_version,
        "tool_status": result.status.value,
        "status": "ok" if succeeded else "blocked" if blocked else "error",
        "execution_state": result.execution_state.value,
        "error_code": result.error.code if result.error else None,
        "elapsed_ms": result.elapsed_ms,
        "duration_ms": result.elapsed_ms,
        "row_count": result.row_count,
        "arguments": observation["arguments"],
        "sources": sources,
    }
    event = {
        "event": "tool_finished",
        "type": "tool_finished",
        "call_id": result.call_id,
        "tool": result.tool_name,
        "tool_status": result.status.value,
        "status": "ok" if succeeded else "blocked" if blocked else "error",
        "execution_state": result.execution_state.value,
        "error_code": result.error.code if result.error else None,
        "elapsed_ms": result.elapsed_ms,
        "duration_ms": result.elapsed_ms,
        "row_count": result.row_count,
    }
    return ToolResultProjection(observation, trace, sources, sources, event)
