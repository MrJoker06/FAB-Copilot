"""Optional equipment-health aggregate capability for explicit compositions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from ...agent_runtime.tools.contracts import ToolExecutionContext, ToolResult
from ...agent_runtime.tools.definition import ToolBinding, ToolDefinition
from .binding import prepare_equipment_health
from .contracts import EquipmentHealthInput, EquipmentHealthPort
from .handler import EquipmentHealthDependencies, equipment_health_handler


def _validate_summary(value: object) -> object:
    required = {"equipment_count", "critical", "watch", "healthy"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("invalid equipment-health summary")
    if any(
        isinstance(value[key], bool)
        or not isinstance(value[key], int)
        or value[key] < 0
        for key in required
    ):
        raise ValueError("invalid equipment-health summary")
    if (
        value["critical"] + value["watch"] + value["healthy"]
        != value["equipment_count"]
    ):
        raise ValueError("inconsistent equipment-health summary")
    return value


EQUIPMENT_HEALTH_SUMMARY_DEFINITION = ToolDefinition(
    "get_equipment_health_summary",
    "1.0.0",
    "汇总设备健康等级数量；需由显式装配启用",
    EquipmentHealthInput,
    _validate_summary,
)


def equipment_health_summary_handler(
    input_value: EquipmentHealthInput,
    context: ToolExecutionContext[EquipmentHealthDependencies],
) -> ToolResult[dict[str, int]]:
    result = equipment_health_handler(input_value, context)
    rows = result.data
    summary = {
        "equipment_count": len(rows),
        "critical": sum(row["health"] == "Critical" for row in rows),
        "watch": sum(row["health"] == "Watch" for row in rows),
        "healthy": sum(row["health"] == "Healthy" for row in rows),
    }
    _validate_summary(summary)
    return ToolResult(
        result.call_id,
        EQUIPMENT_HEALTH_SUMMARY_DEFINITION.name,
        EQUIPMENT_HEALTH_SUMMARY_DEFINITION.version,
        result.status,
        result.execution_state,
        data=summary,
        sources=result.sources,
        row_count=1,
        error=result.error,
    )


def create_equipment_health_summary_binding(
    port: EquipmentHealthPort, *, today: Callable[[], date]
) -> ToolBinding:
    return ToolBinding(
        EQUIPMENT_HEALTH_SUMMARY_DEFINITION,
        equipment_health_summary_handler,
        EquipmentHealthDependencies(port, today),
        prepare_equipment_health,
    )


__all__ = [
    "EQUIPMENT_HEALTH_SUMMARY_DEFINITION",
    "create_equipment_health_summary_binding",
]
