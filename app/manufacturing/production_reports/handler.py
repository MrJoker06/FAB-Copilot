"""Pure handlers for fixed production reports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from ...agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolExecutionState,
    ToolResult,
    ToolSource,
    ToolStatus,
)
from .contracts import (
    FabOverviewInput,
    ProcessPassRateInput,
    ProductionReportDataError,
    ProductionReportQuery,
    ProductionReportSnapshot,
    ProductionReportsPort,
    YieldTrendInput,
    production_report_scope,
    validate_fab_overview_output,
    validate_process_pass_rate_output,
    validate_yield_trend_output,
)


@dataclass(frozen=True, slots=True)
class ProductionReportsDependencies:
    port: ProductionReportsPort
    today: Callable[[], date]


def _snapshot(
    query: ProductionReportQuery,
    context: ToolExecutionContext[ProductionReportsDependencies],
) -> tuple[dict[str, object] | list[dict[str, object]], ToolSource]:
    try:
        snapshot = context.dependencies.port.fetch(query, context.principal)
    except ProductionReportDataError:
        raise
    except Exception as exc:
        raise ProductionReportDataError(
            "production-report source is unavailable"
        ) from exc
    if (
        not isinstance(snapshot, ProductionReportSnapshot)
        or snapshot.query != query
        or snapshot.source.scope != production_report_scope(query, context.principal)
    ):
        raise ProductionReportDataError("source returned an inconsistent scope")
    data = (
        dict(snapshot.data)
        if isinstance(snapshot.data, dict)
        else [dict(row) for row in snapshot.data]
    )
    if query.kind == "overview" and (
        not isinstance(data, dict)
        or data.get("start") != query.start.isoformat()
        or data.get("end") != query.end.isoformat()
    ):
        raise ProductionReportDataError("source returned row outside requested scope")
    if isinstance(data, list):
        for key, expected in (
            ("process_step", query.process_step),
            ("equipment_id", query.equipment_id),
        ):
            if expected is not None and any(row.get(key) != expected for row in data):
                raise ProductionReportDataError(
                    "source returned row outside requested scope"
                )
        if query.kind == "yield":
            for row in data:
                try:
                    week_start = date.fromisoformat(str(row.get("week_start")))
                except ValueError as exc:
                    raise ProductionReportDataError(
                        "source returned row outside requested scope"
                    ) from exc
                if not query.start <= week_start <= query.end:
                    raise ProductionReportDataError(
                        "source returned row outside requested scope"
                    )
        if (
            query.kind == "pass_rate"
            and query.equipment_id is None
            and any(row.get("equipment_id") is not None for row in data)
        ):
            raise ProductionReportDataError(
                "source returned row outside requested scope"
            )
    return data, snapshot.source


def _result(
    name: str,
    input_value: FabOverviewInput | YieldTrendInput | ProcessPassRateInput,
    context: ToolExecutionContext[ProductionReportsDependencies],
    validator: Callable[[object], object],
) -> ToolResult[object]:
    query = input_value.resolve(context.dependencies.today())
    data, source = _snapshot(query, context)
    validator(data)
    return ToolResult(
        context.call_id,
        name,
        "1.0.0",
        ToolStatus.SUCCEEDED,
        ToolExecutionState.COMPLETED,
        data=data,
        sources=(source,),
        row_count=1 if isinstance(data, dict) else len(data),
    )


def fab_overview_handler(
    input_value: FabOverviewInput,
    context: ToolExecutionContext[ProductionReportsDependencies],
) -> ToolResult[object]:
    return _result(
        "get_fab_overview", input_value, context, validate_fab_overview_output
    )


def yield_trend_handler(
    input_value: YieldTrendInput,
    context: ToolExecutionContext[ProductionReportsDependencies],
) -> ToolResult[object]:
    return _result("get_yield_trend", input_value, context, validate_yield_trend_output)


def process_pass_rate_handler(
    input_value: ProcessPassRateInput,
    context: ToolExecutionContext[ProductionReportsDependencies],
) -> ToolResult[object]:
    return _result(
        "get_process_pass_rate", input_value, context, validate_process_pass_rate_output
    )
