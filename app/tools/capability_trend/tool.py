"""Definition, handler and binding for ``get_capability_trend``."""

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
from ...agent_runtime.tools.definition import (
    ToolBinding,
    ToolDefinition,
    ToolPreparation,
)
from .contracts import (
    OUTPUT_SCHEMA,
    TOOL_NAME,
    TOOL_VERSION,
    CapabilityTrendDataError,
    CapabilityTrendInput,
    CapabilityTrendPort,
    CapabilityTrendSnapshot,
    capability_trend_scope,
    validate_capability_trend_output,
    validate_rows_in_scope,
)

CAPABILITY_TREND_DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    version=TOOL_VERSION,
    description="按周查询设备级 Cpk、均值、波动与规格限趋势，可按制程站点和设备过滤",
    input_model=CapabilityTrendInput,
    output_validator=validate_capability_trend_output,
    title="制程能力周趋势",
    output_schema=OUTPUT_SCHEMA,
)


@dataclass(frozen=True, slots=True)
class CapabilityTrendDependencies:
    port: CapabilityTrendPort
    today: Callable[[], date]


def capability_trend_handler(
    input_value: CapabilityTrendInput,
    context: ToolExecutionContext[CapabilityTrendDependencies],
) -> ToolResult[list[dict[str, object]]]:
    query = input_value.resolve(context.dependencies.today())
    try:
        snapshot = context.dependencies.port.fetch(query, context.principal)
    except CapabilityTrendDataError:
        raise
    except Exception as exc:
        raise CapabilityTrendDataError("capability-trend source is unavailable") from exc
    if not isinstance(snapshot, CapabilityTrendSnapshot):
        raise CapabilityTrendDataError("source returned an invalid snapshot")
    if snapshot.query != query or snapshot.source.scope != capability_trend_scope(
        query, context.principal
    ):
        raise CapabilityTrendDataError("source returned an inconsistent scope")
    rows = [dict(row) for row in snapshot.rows]
    validate_capability_trend_output(rows)
    validate_rows_in_scope(query, rows)
    return ToolResult(
        context.call_id,
        TOOL_NAME,
        TOOL_VERSION,
        ToolStatus.SUCCEEDED,
        ToolExecutionState.COMPLETED,
        data=rows,
        sources=(snapshot.source,),
        row_count=len(rows),
    )


def prepare_capability_trend(
    input_value: CapabilityTrendInput,
    context: ToolExecutionContext[CapabilityTrendDependencies],
) -> ToolPreparation[CapabilityTrendInput]:
    query = input_value.resolve(context.dependencies.today())
    return ToolPreparation(
        query.to_input(), capability_trend_scope(query, context.principal)
    )


def create_capability_trend_binding(
    port: CapabilityTrendPort, *, today: Callable[[], date]
) -> ToolBinding[
    CapabilityTrendInput, CapabilityTrendDependencies, list[dict[str, object]]
]:
    return ToolBinding(
        CAPABILITY_TREND_DEFINITION,
        capability_trend_handler,
        CapabilityTrendDependencies(port, today),
        prepare_capability_trend,
    )
