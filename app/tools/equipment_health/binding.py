"""Explicit construction of the unregistered equipment-health pilot binding."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from app.agent_runtime.tools.contracts import ToolExecutionContext, ToolScope
from app.agent_runtime.tools.definition import (
    ToolBinding,
    ToolDefinition,
    ToolPreparation,
)
from app.tools.equipment_health.contracts import (
    EQUIPMENT_HEALTH_OUTPUT_SCHEMA,
    EquipmentHealthInput,
    EquipmentHealthPort,
    validate_equipment_health_output,
)
from app.tools.equipment_health.handler import EquipmentHealthDependencies, equipment_health_handler

EQUIPMENT_HEALTH_DEFINITION = ToolDefinition(
    name="get_equipment_health",
    version="1.0.0",
    description="查询设备运行数、异常数、缺陷密度、停机和健康状态，可按站点或设备过滤",
    input_model=EquipmentHealthInput,
    output_validator=validate_equipment_health_output,
    title="设备健康",
    output_schema=EQUIPMENT_HEALTH_OUTPUT_SCHEMA,
)


def prepare_equipment_health(
    input_value: EquipmentHealthInput,
    context: ToolExecutionContext[EquipmentHealthDependencies],
) -> ToolPreparation[EquipmentHealthInput]:
    """Freeze defaults and expose the exact effective scope before execution."""
    query = input_value.resolve(context.dependencies.today())
    prepared = EquipmentHealthInput(
        start=query.start.isoformat(),
        end=query.end.isoformat(),
        process_step=query.process_step,
        equipment_id=query.equipment_id,
    )
    return ToolPreparation(
        prepared,
        ToolScope(
            context.principal.tenant_id,
            query.start,
            query.end,
            (query.equipment_id,) if query.equipment_id else (),
            (query.process_step,) if query.process_step else (),
            grain="equipment",
        ),
    )


def create_equipment_health_binding(
    port: EquipmentHealthPort, *, today: Callable[[], date]
) -> ToolBinding[
    EquipmentHealthInput, EquipmentHealthDependencies, list[dict[str, object]]
]:
    return ToolBinding(
        EQUIPMENT_HEALTH_DEFINITION,
        equipment_health_handler,
        EquipmentHealthDependencies(port, today),
        prepare_equipment_health,
    )
