"""Consumer-owned equipment-health handler with no registry or SQL knowledge."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from ...agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolExecutionState,
    ToolResult,
    ToolScope,
    ToolStatus,
)
from .contracts import (
    EquipmentHealthDataError,
    EquipmentHealthInput,
    EquipmentHealthPort,
    EquipmentHealthQuery,
    validate_equipment_health_output,
)


@dataclass(frozen=True, slots=True)
class EquipmentHealthDependencies:
    port: EquipmentHealthPort
    today: Callable[[], date]


def _health(row) -> str:
    if row.excursions >= 8 or row.downtime_minutes >= 500:
        return "Critical"
    if row.excursions >= 3 or row.downtime_minutes >= 200:
        return "Watch"
    return "Healthy"


_HEALTH_RANK = {"Critical": 0, "Watch": 1, "Healthy": 2}


def equipment_health_handler(
    input_value: EquipmentHealthInput,
    context: ToolExecutionContext[EquipmentHealthDependencies],
) -> ToolResult[list[dict[str, object]]]:
    deps = context.dependencies
    query: EquipmentHealthQuery = input_value.resolve(deps.today())
    snapshot = deps.port.fetch(query, context.principal)
    expected_scope = ToolScope(
        context.principal.tenant_id,
        query.start,
        query.end,
        (query.equipment_id,) if query.equipment_id else (),
        (query.process_step,) if query.process_step else (),
        grain="equipment",
    )
    if snapshot.query != query or snapshot.source.scope != expected_scope:
        raise EquipmentHealthDataError("source returned an inconsistent scope")
    if query.equipment_id and any(
        row.equipment_id != query.equipment_id for row in snapshot.rows
    ):
        raise EquipmentHealthDataError(
            "source returned equipment outside requested scope"
        )
    rows = []
    for aggregate in snapshot.rows:
        rows.append(
            {
                "equipment_id": aggregate.equipment_id,
                "runs": aggregate.runs,
                "excursions": aggregate.excursions,
                "avg_defect_density": aggregate.avg_defect_density,
                "pass_pct": aggregate.pass_pct,
                "events": aggregate.events,
                "downtime_minutes": aggregate.downtime_minutes,
                "health": _health(aggregate),
            }
        )
    rows.sort(
        key=lambda row: (
            _HEALTH_RANK[row["health"]],
            -int(row["excursions"]),
            -float(row["downtime_minutes"]),
        )
    )
    validate_equipment_health_output(rows)
    return ToolResult(
        context.call_id,
        "get_equipment_health",
        "1.0.0",
        ToolStatus.SUCCEEDED,
        ToolExecutionState.COMPLETED,
        data=rows,
        sources=(snapshot.source,),
        row_count=len(rows),
    )
