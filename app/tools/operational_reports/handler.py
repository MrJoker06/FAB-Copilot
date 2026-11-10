"""Pure handlers for fixed operational manufacturing reports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolExecutionState,
    ToolResult,
    ToolSource,
    ToolStatus,
)
from app.tools.operational_reports.contracts import (
    DefectParetoInput,
    EquipmentProductivityInput,
    OperationalReportDataError,
    OperationalReportQuery,
    OperationalReportSnapshot,
    OperationalReportsPort,
    RecentExcursionsInput,
    operational_report_scope,
    validate_defect_pareto_output,
    validate_equipment_productivity_output,
    validate_recent_excursions_output,
)

OperationalInput = (
    EquipmentProductivityInput | DefectParetoInput | RecentExcursionsInput
)


@dataclass(frozen=True, slots=True)
class OperationalReportsDependencies:
    port: OperationalReportsPort
    today: Callable[[], date]


def _snapshot(
    query: OperationalReportQuery,
    context: ToolExecutionContext[OperationalReportsDependencies],
) -> tuple[list[dict[str, object]], ToolSource]:
    try:
        snapshot = context.dependencies.port.fetch(query, context.principal)
    except OperationalReportDataError:
        raise
    except Exception as exc:
        raise OperationalReportDataError(
            "operational-report source is unavailable"
        ) from exc
    if (
        not isinstance(snapshot, OperationalReportSnapshot)
        or snapshot.query != query
        or snapshot.source.scope != operational_report_scope(query, context.principal)
    ):
        raise OperationalReportDataError("source returned an inconsistent scope")
    rows = [dict(row) for row in snapshot.rows]
    if query.limit is not None and len(rows) > query.limit:
        raise OperationalReportDataError("source returned too many rows")
    if query.kind == "productivity":
        for row in rows:
            equipment = row.get("equipment_id")
            if not isinstance(equipment, str):
                raise OperationalReportDataError(
                    "source returned row outside requested scope"
                )
            if query.equipment_id is not None and equipment != query.equipment_id:
                raise OperationalReportDataError(
                    "source returned row outside requested scope"
                )
            if query.process_step is not None and not equipment.upper().startswith(
                f"{query.process_step}-"
            ):
                raise OperationalReportDataError(
                    "source returned row outside requested scope"
                )
    elif query.kind == "defects" and query.process_step is not None:
        for row in rows:
            processes = row.get("process_steps")
            if not isinstance(processes, str) or not processes:
                raise OperationalReportDataError(
                    "source returned row outside requested scope"
                )
            if any(item != query.process_step for item in processes.split(",")):
                raise OperationalReportDataError(
                    "source returned row outside requested scope"
                )
    elif query.kind == "excursions":
        for row in rows:
            if (
                query.process_step is not None
                and row.get("process_step") != query.process_step
            ):
                raise OperationalReportDataError(
                    "source returned row outside requested scope"
                )
            if (
                query.equipment_id is not None
                and row.get("equipment_id") != query.equipment_id
            ):
                raise OperationalReportDataError(
                    "source returned row outside requested scope"
                )
            value = row.get("run_time")
            try:
                if not isinstance(value, str):
                    raise TypeError("run_time must be a string")
                run_date = (
                    date.fromisoformat(value)
                    if len(value) == 10
                    else datetime.fromisoformat(value).date()
                )
            except (TypeError, ValueError) as exc:
                raise OperationalReportDataError(
                    "source returned row outside requested scope"
                ) from exc
            if not query.start <= run_date <= query.end:
                raise OperationalReportDataError(
                    "source returned row outside requested scope"
                )
    return rows, snapshot.source


def _result(
    name: str,
    input_value: OperationalInput,
    context: ToolExecutionContext[OperationalReportsDependencies],
    validator: Callable[[object], object],
) -> ToolResult[list[dict[str, object]]]:
    query = input_value.resolve(context.dependencies.today())
    rows, source = _snapshot(query, context)
    validator(rows)
    return ToolResult(
        context.call_id,
        name,
        "1.0.0",
        ToolStatus.SUCCEEDED,
        ToolExecutionState.COMPLETED,
        data=rows,
        sources=(source,),
        row_count=len(rows),
    )


def equipment_productivity_handler(
    input_value: EquipmentProductivityInput,
    context: ToolExecutionContext[OperationalReportsDependencies],
) -> ToolResult[list[dict[str, object]]]:
    return _result(
        "get_equipment_productivity",
        input_value,
        context,
        validate_equipment_productivity_output,
    )


def defect_pareto_handler(
    input_value: DefectParetoInput,
    context: ToolExecutionContext[OperationalReportsDependencies],
) -> ToolResult[list[dict[str, object]]]:
    return _result(
        "get_defect_pareto", input_value, context, validate_defect_pareto_output
    )


def recent_excursions_handler(
    input_value: RecentExcursionsInput,
    context: ToolExecutionContext[OperationalReportsDependencies],
) -> ToolResult[list[dict[str, object]]]:
    return _result(
        "get_recent_excursions",
        input_value,
        context,
        validate_recent_excursions_output,
    )
