"""Pure handlers for consumer-owned process diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from ...agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolExecutionState,
    ToolResult,
    ToolStatus,
)
from .contracts import (
    DiagnosticsDataError,
    DiagnosticsQuery,
    DiagnosticsSnapshot,
    ProcessCapabilityInput,
    ProcessDiagnosticsPort,
    SensorSummaryInput,
    diagnostics_scope,
    validate_process_capability_output,
    validate_sensor_summary_output,
)


@dataclass(frozen=True, slots=True)
class ProcessDiagnosticsDependencies:
    port: ProcessDiagnosticsPort
    today: Callable[[], date]


def _snapshot_rows(
    query: DiagnosticsQuery,
    context: ToolExecutionContext[ProcessDiagnosticsDependencies],
) -> tuple[list[dict[str, object]], object]:
    try:
        snapshot = context.dependencies.port.fetch(query, context.principal)
    except DiagnosticsDataError:
        raise
    except Exception as exc:
        raise DiagnosticsDataError("process-diagnostics source is unavailable") from exc
    if not isinstance(snapshot, DiagnosticsSnapshot):
        raise DiagnosticsDataError("source returned an invalid snapshot")
    if snapshot.query != query or snapshot.source.scope != diagnostics_scope(
        query, context.principal
    ):
        raise DiagnosticsDataError("source returned an inconsistent scope")
    rows = list(snapshot.rows)
    for field, expected in (
        ("process_step", query.process_step),
        ("equipment_id", query.equipment_id),
        ("signal_name", query.signal_name),
    ):
        if expected is not None and any(row.get(field) != expected for row in rows):
            raise DiagnosticsDataError("source returned row outside requested scope")
    return rows, snapshot.source


def process_capability_handler(
    input_value: ProcessCapabilityInput,
    context: ToolExecutionContext[ProcessDiagnosticsDependencies],
) -> ToolResult[list[dict[str, object]]]:
    query = input_value.resolve(context.dependencies.today())
    rows, source = _snapshot_rows(query, context)
    validate_process_capability_output(rows)
    return ToolResult(
        context.call_id,
        "get_process_capability",
        "1.0.0",
        ToolStatus.SUCCEEDED,
        ToolExecutionState.COMPLETED,
        data=rows,
        sources=(source,),
        row_count=len(rows),
    )


def sensor_summary_handler(
    input_value: SensorSummaryInput,
    context: ToolExecutionContext[ProcessDiagnosticsDependencies],
) -> ToolResult[list[dict[str, object]]]:
    query = input_value.resolve(context.dependencies.today())
    rows, source = _snapshot_rows(query, context)
    validate_sensor_summary_output(rows)
    return ToolResult(
        context.call_id,
        "get_sensor_summary",
        "1.0.0",
        ToolStatus.SUCCEEDED,
        ToolExecutionState.COMPLETED,
        data=rows,
        sources=(source,),
        row_count=len(rows),
    )
