"""Unregistered native definitions for fixed operational reports."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from ...agent_runtime.tools.contracts import ToolExecutionContext
from ...agent_runtime.tools.definition import (
    ToolBinding,
    ToolDefinition,
    ToolPreparation,
)
from .contracts import (
    DefectParetoInput,
    EquipmentProductivityInput,
    OperationalReportsPort,
    RecentExcursionsInput,
    operational_report_scope,
    validate_defect_pareto_output,
    validate_equipment_productivity_output,
    validate_recent_excursions_output,
)
from .handler import (
    OperationalReportsDependencies,
    defect_pareto_handler,
    equipment_productivity_handler,
    recent_excursions_handler,
)

EQUIPMENT_PRODUCTIVITY_DEFINITION = ToolDefinition(
    "get_equipment_productivity",
    "1.0.0",
    "查询设备生产、待机、工程和停机时间占比，可按站点或设备过滤",
    EquipmentProductivityInput,
    validate_equipment_productivity_output,
)
DEFECT_PARETO_DEFINITION = ToolDefinition(
    "get_defect_pareto",
    "1.0.0",
    "查询缺陷类型 Pareto 和受影响批次数，可按站点过滤",
    DefectParetoInput,
    validate_defect_pareto_output,
)
RECENT_EXCURSIONS_DEFINITION = ToolDefinition(
    "get_recent_excursions",
    "1.0.0",
    "查询最近的制程异常批次及量测值，可按站点或设备过滤",
    RecentExcursionsInput,
    validate_recent_excursions_output,
)


def prepare_equipment_productivity(
    input_value: EquipmentProductivityInput,
    context: ToolExecutionContext[OperationalReportsDependencies],
) -> ToolPreparation[EquipmentProductivityInput]:
    query = input_value.resolve(context.dependencies.today())
    return ToolPreparation(
        EquipmentProductivityInput(
            query.start.isoformat(),
            query.end.isoformat(),
            query.process_step,
            query.equipment_id,
        ),
        operational_report_scope(query, context.principal),
    )


def prepare_defect_pareto(
    input_value: DefectParetoInput,
    context: ToolExecutionContext[OperationalReportsDependencies],
) -> ToolPreparation[DefectParetoInput]:
    query = input_value.resolve(context.dependencies.today())
    return ToolPreparation(
        DefectParetoInput(
            query.start.isoformat(),
            query.end.isoformat(),
            query.process_step,
            query.limit or 10,
        ),
        operational_report_scope(query, context.principal),
    )


def prepare_recent_excursions(
    input_value: RecentExcursionsInput,
    context: ToolExecutionContext[OperationalReportsDependencies],
) -> ToolPreparation[RecentExcursionsInput]:
    query = input_value.resolve(context.dependencies.today())
    return ToolPreparation(
        RecentExcursionsInput(
            query.start.isoformat(),
            query.end.isoformat(),
            query.process_step,
            query.equipment_id,
            query.limit or 20,
        ),
        operational_report_scope(query, context.principal),
    )


def create_equipment_productivity_binding(
    port: OperationalReportsPort, *, today: Callable[[], date]
) -> ToolBinding[
    EquipmentProductivityInput, OperationalReportsDependencies, list[dict[str, object]]
]:
    return ToolBinding(
        EQUIPMENT_PRODUCTIVITY_DEFINITION,
        equipment_productivity_handler,
        OperationalReportsDependencies(port, today),
        prepare_equipment_productivity,
    )


def create_defect_pareto_binding(
    port: OperationalReportsPort, *, today: Callable[[], date]
) -> ToolBinding[
    DefectParetoInput, OperationalReportsDependencies, list[dict[str, object]]
]:
    return ToolBinding(
        DEFECT_PARETO_DEFINITION,
        defect_pareto_handler,
        OperationalReportsDependencies(port, today),
        prepare_defect_pareto,
    )


def create_recent_excursions_binding(
    port: OperationalReportsPort, *, today: Callable[[], date]
) -> ToolBinding[
    RecentExcursionsInput, OperationalReportsDependencies, list[dict[str, object]]
]:
    return ToolBinding(
        RECENT_EXCURSIONS_DEFINITION,
        recent_excursions_handler,
        OperationalReportsDependencies(port, today),
        prepare_recent_excursions,
    )
