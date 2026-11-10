"""Explicit, unregistered bindings for process diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from app.agent_runtime.tools.contracts import ToolExecutionContext
from app.agent_runtime.tools.definition import (
    ToolBinding,
    ToolDefinition,
    ToolPreparation,
)
from app.tools.process_diagnostics.contracts import (
    PROCESS_CAPABILITY_OUTPUT_SCHEMA,
    SENSOR_SUMMARY_OUTPUT_SCHEMA,
    ProcessCapabilityInput,
    ProcessDiagnosticsPort,
    SensorSummaryInput,
    diagnostics_scope,
    validate_process_capability_output,
    validate_sensor_summary_output,
)
from app.tools.process_diagnostics.handler import (
    ProcessDiagnosticsDependencies,
    process_capability_handler,
    sensor_summary_handler,
)

PROCESS_CAPABILITY_DEFINITION = ToolDefinition(
    name="get_process_capability",
    version="1.0.0",
    description="查询制程能力、规格范围与 Cpk，可按制程站点过滤",
    input_model=ProcessCapabilityInput,
    output_validator=validate_process_capability_output,
    title="制程能力 Cpk",
    output_schema=PROCESS_CAPABILITY_OUTPUT_SCHEMA,
)
SENSOR_SUMMARY_DEFINITION = ToolDefinition(
    name="get_sensor_summary",
    version="1.0.0",
    description="查询传感器样本、缺失、异常和统计摘要，可联合按站点、设备和信号过滤",
    input_model=SensorSummaryInput,
    output_validator=validate_sensor_summary_output,
    title="传感器统计摘要",
    output_schema=SENSOR_SUMMARY_OUTPUT_SCHEMA,
)


def prepare_process_capability(
    input_value: ProcessCapabilityInput,
    context: ToolExecutionContext[ProcessDiagnosticsDependencies],
) -> ToolPreparation[ProcessCapabilityInput]:
    query = input_value.resolve(context.dependencies.today())
    return ToolPreparation(
        ProcessCapabilityInput(
            query.start.isoformat(), query.end.isoformat(), query.process_step
        ),
        diagnostics_scope(query, context.principal),
    )


def prepare_sensor_summary(
    input_value: SensorSummaryInput,
    context: ToolExecutionContext[ProcessDiagnosticsDependencies],
) -> ToolPreparation[SensorSummaryInput]:
    query = input_value.resolve(context.dependencies.today())
    return ToolPreparation(
        SensorSummaryInput(
            query.start.isoformat(),
            query.end.isoformat(),
            query.process_step,
            query.equipment_id,
            query.signal_name,
        ),
        diagnostics_scope(query, context.principal),
    )


def create_process_capability_binding(
    port: ProcessDiagnosticsPort, *, today: Callable[[], date]
) -> ToolBinding[
    ProcessCapabilityInput, ProcessDiagnosticsDependencies, list[dict[str, object]]
]:
    return ToolBinding(
        PROCESS_CAPABILITY_DEFINITION,
        process_capability_handler,
        ProcessDiagnosticsDependencies(port, today),
        prepare_process_capability,
    )


def create_sensor_summary_binding(
    port: ProcessDiagnosticsPort, *, today: Callable[[], date]
) -> ToolBinding[
    SensorSummaryInput, ProcessDiagnosticsDependencies, list[dict[str, object]]
]:
    return ToolBinding(
        SENSOR_SUMMARY_DEFINITION,
        sensor_summary_handler,
        ProcessDiagnosticsDependencies(port, today),
        prepare_sensor_summary,
    )
